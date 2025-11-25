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
        
        # 🐢 超安全频率控制
        self.last_scan_time = 0
        self.min_scan_interval = 30  # 最小扫描间隔30秒
        self.scan_count_today = 0
        self.daily_scan_limit = 500  # 每日最多500次扫描
        self.last_reset_time = time.time()
        
        # API限制管理
        self.api_limit_errors = 0
        self.last_api_limit_time = 0
        self.consecutive_checks = 0
        
    async def start_listening(self):
        """开始监听事件 - 大幅降低频率"""
        self.is_running = True
        self.logger.info("🚀 启动超安全监听模式...")
        
        # 等待更长时间再开始，避免启动风暴
        await asyncio.sleep(10)
        
        while self.is_running:
            try:
                ws_url = await self.node_manager.get_current_websocket_url()
                if not ws_url:
                    self.logger.warning("没有可用的WebSocket URL，等待30秒后重试...")
                    await asyncio.sleep(30)
                    continue
                    
                await self._listen_websocket_super_safe(ws_url)
                
            except Exception as e:
                self.logger.error(f"WebSocket监听失败: {e}")
                await asyncio.sleep(30)
    
    async def _listen_websocket_super_safe(self, ws_url):
        """🐢 超安全监听模式 - 大幅降低频率"""
        try:
            async with connect(ws_url) as ws:
                self.logger.info(f"✅ 成功连接到WebSocket: {ws_url}")
                
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
                self.logger.info(f"📨 订阅响应: {response}")
                
                self.consecutive_checks = 0
                self.last_scan_time = 0
                
                while self.is_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=60)
                        data = json.loads(message)
                        
                        if 'params' in data and data['params'].get('subscription'):
                            self.consecutive_checks += 1
                            
                            current_time = time.time()
                            
                            # 🐢 超安全频率控制策略
                            # 策略1：每日扫描次数限制
                            if self._exceeded_daily_limit():
                                self.logger.warning("📊 达到每日扫描限制，跳过检查")
                                continue
                            
                            # 策略2：最小时间间隔限制（30秒）
                            if current_time - self.last_scan_time < self.min_scan_interval:
                                wait_time = self.min_scan_interval - (current_time - self.last_scan_time)
                                self.logger.debug(f"⏰ 时间间隔限制，还需等待{wait_time:.1f}秒")
                                continue
                            
                            # 策略3：API限制冷却期
                            if self.api_limit_errors > 0 and current_time - self.last_api_limit_time < 60:
                                remaining = 60 - (current_time - self.last_api_limit_time)
                                self.logger.debug(f"❄️ API限制冷却中，还需等待{remaining:.1f}秒")
                                continue
                            
                            # 策略4：大幅降低检查频率
                            # 每10个块检查一次（约30秒）
                            if self.consecutive_checks % 10 == 0:
                                self.logger.info("🔍 低频检查：收到新块通知")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                asyncio.create_task(self._ultra_safe_scan(1))
                            
                            # 策略5：每60个块做一次深度检查（约3分钟）
                            elif self.consecutive_checks % 60 == 0:
                                self.logger.info("📊 超低频深度检查")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                asyncio.create_task(self._ultra_safe_scan(2))
                            
                            else:
                                self.logger.debug("⏭️ 跳过：超安全频率控制")
                                continue
                                
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                            self.logger.debug("💓 发送心跳包")
                        except Exception:
                            self.logger.warning("💔 心跳发送失败，重新连接...")
                            break
                    except Exception as e:
                        self.logger.error(f"WebSocket接收错误: {e}")
                        break
                        
        except Exception as e:
            self.logger.error(f"WebSocket连接失败 {ws_url}: {e}")
            self.node_manager.mark_websocket_unhealthy(ws_url)
    
    def _exceeded_daily_limit(self):
        """检查是否超过每日扫描限制"""
        current_time = time.time()
        # 每天重置计数
        if current_time - self.last_reset_time > 86400:
            self.scan_count_today = 0
            self.last_reset_time = current_time
            self.logger.info("🔄 每日扫描计数器已重置")
        
        if self.scan_count_today >= self.daily_scan_limit:
            return True
        return False
    
    async def _ultra_safe_scan(self, block_range=1):
        """🐢 超安全扫描方法"""
        # 前置检查
        if not await self._can_make_request():
            return

        try:
            # 获取最新区块
            latest_block = await self.node_manager.make_http_request('get_block', 'latest')
            if not latest_block:
                return
                
            block_number = latest_block.number
            
            # 超安全扫描：只扫描最新1个块
            from_block = block_number
            to_block = block_number
            
            self.logger.info(f"🐢 超安全扫描: 区块 {from_block} (今日扫描: {self.scan_count_today}/{self.daily_scan_limit})")
            
            # 使用超安全扫描方法
            await self._scan_blocks_ultra_safe(from_block, to_block)
                
        except Exception as e:
            self.logger.error(f"超安全扫描失败: {e}")
    
    async def _scan_blocks_ultra_safe(self, from_block, to_block):
        """🐢 超安全扫描 - 最保守的策略"""
        try:
            if from_block > to_block:
                from_block, to_block = to_block, from_block
            
            # 超安全扫描：严格限制范围
            max_block_range = 1
            if to_block - from_block > max_block_range:
                to_block = from_block + max_block_range
                self.logger.warning(f"⚠️ 扫描范围过大，调整为: {from_block}-{to_block}")
            
            # 获取合约实例
            factory_contract = await self._get_factory_contract()
            if not factory_contract:
                self.logger.error("无法获取工厂合约实例")
                return 0
            
            loop = asyncio.get_event_loop()
            events = await loop.run_in_executor(
                None,
                lambda: factory_contract.events.PairCreated.get_logs(
                    fromBlock=from_block,
                    toBlock=to_block
                )
            )
            
            # 重置API限制错误计数（成功扫描后）
            if self.api_limit_errors > 0:
                self.logger.info("✅ API限制错误计数重置")
                self.api_limit_errors = 0
            
            new_pairs_found = 0
            for event in events:
                token_address = event.args.token0
                pair_address = event.args.pair
                
                cache_key = f"pair_{pair_address}"
                if self.cache_manager.exists('detected_pairs', cache_key):
                    continue
                
                self.logger.info(f"🎯 发现新交易对: {token_address} -> {pair_address}")
                
                self.cache_manager.set('detected_pairs', cache_key, True, 3600)
                await self._process_new_token(token_address, pair_address)
                new_pairs_found += 1
            
            if new_pairs_found > 0:
                self.logger.info(f"✅ 超安全扫描完成: 发现 {new_pairs_found} 个新交易对")
            else:
                self.logger.debug(f"超安全扫描完成: 区块 {from_block} 无新交易对")
                
            return new_pairs_found
            
        except Exception as e:
            error_msg = str(e)
            
            # API限制特殊处理
            if 'limit exceeded' in error_msg or 'rate limit' in error_msg or '32005' in error_msg:
                self.api_limit_errors += 1
                self.last_api_limit_time = time.time()
                
                # 超安全模式：遇到限制暂停更长时间
                if self.api_limit_errors == 1:
                    self.logger.warning("⚠️ 遇到API限制，暂停60秒")
                    await asyncio.sleep(60)
                elif self.api_limit_errors == 2:
                    self.logger.warning("⚠️ 再次遇到API限制，暂停120秒")
                    await asyncio.sleep(120)
                else:
                    self.logger.warning("🚨 频繁遇到API限制，暂停300秒")
                    await asyncio.sleep(300)
            
            self.logger.error(f"超安全扫描失败 {from_block}-{to_block}: {e}")
            return 0
    
    async def _get_factory_contract(self):
        """获取工厂合约实例"""
        try:
            if not self.node_manager.http_nodes:
                self.logger.error("❌ 没有可用的HTTP节点")
                return None

            healthy_nodes = [node for node in self.node_manager.http_nodes 
                            if node.get('healthy', True)]
            
            if not healthy_nodes:
                self.logger.error("❌ 所有HTTP节点都不可用")
                return None

            # 选择第一个健康节点
            node = healthy_nodes[0]
            w3_instance = node['w3']
            factory_contract = w3_instance.eth.contract(
                address=Web3.to_checksum_address(self.config.PANCAKE_FACTORY),
                abi=self.config.PANCAKE_FACTORY_ABI
            )
            
            return factory_contract
            
        except Exception as e:
            self.logger.error(f"获取工厂合约失败: {e}")
            return None
    
    async def _process_new_token(self, token_address, pair_address):
        """处理新代币检测"""
        try:
            self.logger.info(f"🚨 处理新代币: {token_address}")
            await self._execute_detection_immediately(token_address, pair_address)
                
        except Exception as e:
            self.logger.error(f"代币处理失败 {token_address}: {e}")
    
    async def _execute_detection_immediately(self, token_address, pair_address):
        """立即执行代币检测"""
        try:
            from risk_detector import RiskDetector
            from notification_manager import NotificationManager
            
            detector = RiskDetector(self.config, self.node_manager, self.cache_manager)
            
            start_time = asyncio.get_event_loop().time()
            
            risk_report = await detector.detect_risks(token_address, pair_address)
            detection_time = asyncio.get_event_loop().time() - start_time
            
            self.logger.info(f"✅ 代币检测完成: {token_address}, 耗时: {detection_time:.2f}秒")
            
            # 发送通知
            notifier = NotificationManager(self.config)
            await notifier.send_dingtalk_notification(risk_report, detection_time)
            
        except Exception as e:
            self.logger.error(f"代币检测流程失败 {token_address}: {e}")
    
    async def _can_make_request(self):
        """检查是否可以进行API调用"""
        # 简单的节流检查
        return True
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("事件监听器已停止")
