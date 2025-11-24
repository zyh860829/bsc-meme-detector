import asyncio
import json
import logging
import time
from web3 import Web3
from websockets import connect


class EventListener:
    def __init__(self, config, node_manager, cache_manager):
        self.config = config
        self.node_manager = node_manager
        self.cache_manager = cache_manager
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        
        # 添加频率限制控制
        self.last_check_time = 0
        self.check_interval = 30  # 每30秒检查一次新交易对
        
        # 延迟初始化合约，避免启动时立即调用API
        self.factory_contract = None
    
    async def start_listening(self):
        """开始监听事件"""
        self.is_running = True
        self.logger.info("开始监听BSC链上事件...")
        
        # 延迟初始化合约
        if not self.factory_contract:
            await self._initialize_contract()
        
        # 等待一段时间再开始，避免启动风暴
        await asyncio.sleep(10)
        
        while self.is_running:
            try:
                ws_url = await self.node_manager.get_current_websocket_url()
                if not ws_url:
                    self.logger.warning("没有可用的WebSocket URL，等待10秒后重试...")
                    await asyncio.sleep(10)
                    continue
                    
                await self._listen_websocket(ws_url)
                
            except Exception as e:
                self.logger.error(f"WebSocket监听失败: {e}")
                await asyncio.sleep(10)
    
    async def _initialize_contract(self):
        """延迟初始化合约"""
        try:
            self.factory_contract = self.node_manager.http_nodes[0]['w3'].eth.contract(
                address=Web3.to_checksum_address(self.config.PANCAKE_FACTORY),
                abi=self.config.PANCAKE_FACTORY_ABI
            )
            self.logger.info("PancakeSwap Factory合约初始化成功")
        except Exception as e:
            self.logger.error(f"合约初始化失败: {e}")
    
    async def _listen_websocket(self, ws_url):
        """监听WebSocket事件"""
        try:
            async with connect(ws_url) as ws:
                self.logger.info(f"成功连接到WebSocket: {ws_url}")
                
                # 订阅新块事件
                subscription_message = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["newHeads"]
                }
                await ws.send(json.dumps(subscription_message))
                
                # 等待订阅确认
                response = await ws.recv()
                self.logger.info(f"订阅响应: {response}")
                
                while self.is_running:
                    try:
                        # ✅ 修正：移除多余的await
                        message = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(message)
                        
                        if 'params' in data and data['params'].get('subscription'):
                            self.logger.info("收到新块通知，检查新交易对...")
                            
                            # ✅ 添加频率限制
                            current_time = time.time()
                            if current_time - self.last_check_time >= self.check_interval:
                                self.last_check_time = current_time
                                asyncio.create_task(self._check_new_pairs())
                            else:
                                self.logger.debug("跳过检查：频率限制")
                            
                    except asyncio.TimeoutError:
                        # 发送心跳保持连接
                        try:
                            await ws.ping()
                            self.logger.debug("发送心跳包")
                        except Exception:
                            self.logger.warning("心跳发送失败，重新连接...")
                            break
                    except Exception as e:
                        self.logger.error(f"WebSocket接收错误: {e}")
                        break
                        
        except Exception as e:
            self.logger.error(f"WebSocket连接失败 {ws_url}: {e}")
            # 标记节点不健康
            self.node_manager.mark_websocket_unhealthy(ws_url)
    
    async def _check_new_pairs(self):
        """检查新创建的交易对 - 添加重试机制和频率控制"""
        max_retries = 2
        retry_delay = 5  # 秒
        
        for attempt in range(max_retries):
            try:
                if not self.factory_contract:
                    await self._initialize_contract()
                    if not self.factory_contract:
                        self.logger.error("合约未初始化，跳过检查")
                        return
                
                # 获取最新区块
                latest_block = await self.node_manager.make_http_request('get_block', 'latest')
                block_number = latest_block.number
                
                # ✅ 减少查询范围：只查询最近5个区块
                from_block = max(0, block_number - 5)
                
                self.logger.info(f"查询区块范围: {from_block} - {block_number}")
                
                # 使用线程池执行同步的Web3操作
                loop = asyncio.get_event_loop()
                events = await loop.run_in_executor(
                    None,
                    lambda: self.factory_contract.events.PairCreated.get_logs(
                        fromBlock=from_block,
                        toBlock=block_number
                    )
                )
                
                self.logger.info(f"在区块 {from_block}-{block_number} 中找到 {len(events)} 个事件")
                
                for event in events:
                    token_address = event.args.token0
                    pair_address = event.args.pair
                    
                    # 检查是否已检测过
                    cache_key = f"pair_{pair_address}"
                    if self.cache_manager.exists('detected_pairs', cache_key):
                        continue
                    
                    self.logger.info(f"检测到新交易对: {token_address} -> {pair_address}")
                    
                    # 标记为已检测
                    self.cache_manager.set('detected_pairs', cache_key, True, 3600)
                    
                    # 触发检测流程
                    asyncio.create_task(self._process_new_token(token_address, pair_address))
                
                # 如果成功，跳出重试循环
                break
                
            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"检查新交易对失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}")
                
                # 如果是频率限制错误，等待更长时间
                if 'limit exceeded' in error_msg or '32005' in error_msg:
                    wait_time = retry_delay * (attempt + 1)
                    self.logger.warning(f"API限制，等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                elif attempt < max_retries - 1:  # 不是最后一次尝试
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error("已达到最大重试次数，跳过本次检查")
    
    async def _process_new_token(self, token_address, pair_address):
        """处理新代币检测"""
        try:
            from risk_detector import RiskDetector
            from notification_manager import NotificationManager
            
            # 初始化检测器
            detector = RiskDetector(self.config, self.node_manager, self.cache_manager)
            
            # 执行风险检测
            start_time = asyncio.get_event_loop().time()
            risk_report = await detector.detect_risks(token_address, pair_address)
            detection_time = asyncio.get_event_loop().time() - start_time
            
            self.logger.info(f"代币检测完成: {token_address}, 耗时: {detection_time:.2f}秒")
            
            # 发送通知
            notifier = NotificationManager(self.config)
            await notifier.send_dingtalk_notification(risk_report, detection_time)
            
        except Exception as e:
            self.logger.error(f"代币检测流程失败 {token_address}: {e}")
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("事件监听器已停止")
