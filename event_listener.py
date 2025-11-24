import asyncio
import json
import logging
from web3 import Web3
from websockets import connect


class EventListener:
    def __init__(self, config, node_manager, cache_manager):
        self.config = config
        self.node_manager = node_manager
        self.cache_manager = cache_manager
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        
        # 初始化PancakeSwap Factory合约
        self.factory_contract = node_manager.http_nodes[0]['w3'].eth.contract(
            address=Web3.to_checksum_address(config.PANCAKE_FACTORY),
            abi=config.PANCAKE_FACTORY_ABI
        )
    
    async def start_listening(self):
        """开始监听事件"""
        self.is_running = True
        while self.is_running:
            try:
                ws_url = self.node_manager.get_current_websocket_url()
                await self._listen_websocket(ws_url)
            except Exception as e:
                self.logger.error(f"WebSocket监听失败: {e}")
                await asyncio.sleep(5)
    
    async def _listen_websocket(self, ws_url):
        """监听WebSocket事件"""
        async with connect(ws_url) as ws:
            self.logger.info(f"开始监听WebSocket: {ws_url}")
            
            # 订阅新块事件
            subscription_message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_subscribe",
                "params": ["newHeads"]
            }
            await ws.send(json.dumps(subscription_message))
            
            while self.is_running:
                try:
                    # 👇 修复：对 ws.recv() 加 await，避免 coroutine 错误
                    message = await asyncio.wait_for(await ws.recv(), timeout=30)
                    data = json.loads(message)
                    
                    if 'params' in data and data['params'].get('subscription'):
                        # 收到新块通知，检查新交易对
                        await self._check_new_pairs()
                        
                except asyncio.TimeoutError:
                    # 发送心跳
                    await ws.ping()
                except Exception as e:
                    self.logger.error(f"WebSocket接收错误: {e}")
                    break
    
    async def _check_new_pairs(self):
        """检查新创建的交易对"""
        try:
            # 获取最新区块
            latest_block = await self.node_manager.make_http_request('get_block', 'latest')
            block_number = latest_block.number
            
            # 查询最近50个区块的PairCreated事件
            from_block = max(0, block_number - 50)
            
            events = self.factory_contract.events.PairCreated.get_logs(
                fromBlock=from_block,
                toBlock=block_number
            )
            
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
                await self._process_new_token(token_address, pair_address)
                
        except Exception as e:
            self.logger.error(f"检查新交易对失败: {e}")
    
    async def _process_new_token(self, token_address, pair_address):
        """处理新代币检测"""
        from risk_detector import RiskDetector
        from notification_manager import NotificationManager
        
        try:
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
