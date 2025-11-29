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
        
        # 🎯 新增：智能限制状态管理
        self.is_limit_reached = False
        self.limit_notified = False
        self.limit_reached_time = 0
        
        # API限制管理
        self.api_limit_errors = 0
        self.last_api_limit_time = 0
        self.consecutive_checks = 0
        
        # ✅ 区块去重机制
        self.processed_blocks = set()  # 已处理的区块号集合
        self.last_block_number = 0     # 最后处理的区块号
        self.max_processed_blocks = 1000  # 最大保存的区块数量
        
    async def start_listening(self):
        """开始监听事件 - 大幅降低频率"""
        self.is_running = True
        self.logger.info("🚀 启动超安全监听模式...")
        
        # 等待更长时间再开始，避免启动风暴
        await asyncio.sleep(10)
        
        while self.is_running:
            try:
                # 🎯 新增：达到限制时跳过节点获取
                if self.is_limit_reached:
                    await asyncio.sleep(60)  # 限制状态下等待更长时间
                    continue
                    
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
                            # ✅ 提取区块号并进行去重检查
                            block_data = data['params']['result']
                            block_number_hex = block_data.get('number')
                            if not block_number_hex:
                                continue
                                
                            block_number = int(block_number_hex, 16)
                            
                            # ✅ 区块去重检查
                            if block_number <= self.last_block_number:
                                self.logger.debug(f"⏭️ 跳过旧区块: {block_number} (最后处理: {self.last_block_number})")
                                continue
                                
                            if block_number in self.processed_blocks:
                                self.logger.debug(f"⏭️ 区块 {block_number} 已处理过，跳过")
                                continue
                            
                            self.consecutive_checks += 1
                            current_time = time.time()
                            
                            # 🎯 修改：优先检查每日限制状态
                            if self.is_limit_reached:
                                # 限制状态下，只更新区块状态，不进行扫描
                                self.last_block_number = block_number
                                self.processed_blocks.add(block_number)
                                self._clean_old_blocks()
                                continue
                            
                            # 🐢 超安全频率控制策略
                            # 策略1：每日扫描次数限制
                            if self._exceeded_daily_limit():
                                self._handle_daily_limit_reached()
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
                            
                            # 策略4：保持原有检查频率
                            # 每10个块检查一次（约30秒）- 保持不变
                            if self.consecutive_checks % 10 == 0:
                                self.logger.info("🔍 低频检查：收到新块通知")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                
                                # ✅ 更新区块状态
                                self.last_block_number = block_number
                                self.processed_blocks.add(block_number)
                                
                                # ✅ 清理旧的区块记录
                                self._clean_old_blocks()
                                
                                asyncio.create_task(self._ultra_safe_scan(block_number))
                            
                            # 策略5：保持原有深度检查频率
                            # 每60个块做一次深度检查（约3分钟）- 保持不变
                            elif self.consecutive_checks % 60 == 0:
                                self.logger.info("📊 超低频深度检查")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                
                                # ✅ 更新区块状态
                                self.last_block_number = block_number
                                self.processed_blocks.add(block_number)
                                self._clean_old_blocks()
                                
                                asyncio.create_task(self._ultra_safe_scan(block_number))
                            
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
    
    def _clean_old_blocks(self):
        """✅ 清理旧的区块记录，避免内存泄漏"""
        if len(self.processed_blocks) > self.max_processed_blocks:
            # 移除最旧的区块记录
            blocks_to_remove = sorted(self.processed_blocks)[:self.max_processed_blocks // 2]
            for block in blocks_to_remove:
                self.processed_blocks.remove(block)
            self.logger.debug(f"🧹 清理了 {len(blocks_to_remove)} 个旧的区块记录")
    
    def _exceeded_daily_limit(self):
        """检查是否超过每日扫描限制"""
        current_time = time.time()
        # 每天重置计数
        if current_time - self.last_reset_time > 86400:
            self.scan_count_today = 0
            self.last_reset_time = current_time
            self.processed_blocks.clear()  # ✅ 同时清空已处理区块
            # 🎯 新增：重置限制状态
            self.is_limit_reached = False
            self.limit_notified = False
            self.logger.info("🔄 每日扫描计数器已重置")
        
        if self.scan_count_today >= self.daily_scan_limit:
            return True
        return False
    
    def _handle_daily_limit_reached(self):
        """🎯 新增：处理达到每日限制的情况"""
        if not self.is_limit_reached:
            self.is_limit_reached = True
            self.limit_reached_time = time.time()
            self.logger.info(f"🎯 今日扫描已达上限 {self.scan_count_today}/{self.daily_scan_limit}，进入待机模式")
        
        # 每10分钟提醒一次限制状态
        current_time = time.time()
        if not self.limit_notified or current_time - self.limit_reached_time > 600:
            self.logger.info(f"⏸️ 系统待机中 - 今日扫描: {self.scan_count_today}/{self.daily_scan_limit}")
            self.limit_notified = True
            self.limit_reached_time = current_time
    
    async def _ultra_safe_scan(self, block_number):
        """🐢 超安全扫描方法 - 修改为接收具体区块号"""
        # 🎯 新增：前置限制检查
        if self.is_limit_reached:
            self.logger.debug("⏭️ 达到每日限制，跳过扫描")
            return

        # 前置检查
        if not await self._can_make_request():
            return

        try:
            # ✅ 修改：直接使用传入的区块号，而不是重新获取最新区块
            self.logger.info(f"🐢 超安全扫描: 区块 {block_number} (今日扫描: {self.scan_count_today}/{self.daily_scan_limit})")
            
            # 使用超安全扫描方法
            await self._scan_blocks_ultra_safe(block_number, block_number)
                
        except Exception as e:
            self.logger.error(f"超安全扫描失败: {e}")
    
    async def _scan_blocks_ultra_safe(self, from_block, to_block):
        """🐢 超安全扫描 - 保持原有最保守的策略"""
        # 🎯 新增：限制状态检查
        if self.is_limit_reached:
            self.logger.debug("⏭️ 达到每日限制，跳过区块扫描")
            return 0
            
        try:
            if from_block > to_block:
                from_block, to_block = to_block, from_block
            
            # 🎯 修改：保持原有区块范围限制（1个区块）
            max_block_range = 1  # 保持不变
            if to_block - from_block > max_block_range:
                to_block = from_block + max_block_range
                self.logger.warning(f"⚠️ 扫描范围过大，调整为: {from_block}-{to_block}")
            
            # 🎯 修改：获取多个工厂合约实例
            factory_contracts = await self._get_factory_contracts()
            if not factory_contracts:
                self.logger.error("无法获取工厂合约实例")
                return 0
            
            loop = asyncio.get_event_loop()
            
            new_pairs_found = 0
            # 🎯 修改：遍历所有工厂合约
            for factory in factory_contracts:
                try:
                    events = await loop.run_in_executor(
                        None,
                        lambda f=factory: f['contract'].events.PairCreated.get_logs(
                            fromBlock=from_block,
                            toBlock=to_block
                        )
                    )
                    
                    for event in events:
                        token_address = event.args.token0
                        pair_address = event.args.pair
                        
                        cache_key = f"pair_{pair_address}"
                        if self.cache_manager.exists('detected_pairs', cache_key):
                            continue
                        
                        self.logger.info(f"🎯 从 {factory['name']} 发现新交易对: {token_address} -> {pair_address}")
                        
                        self.cache_manager.set('detected_pairs', cache_key, True, 3600)
                        await self._process_new_token(token_address, pair_address)
                        new_pairs_found += 1
                        
                except Exception as e:
                    self.logger.error(f"扫描工厂 {factory['name']} 失败: {e}")
                    continue
            
            # 重置API限制错误计数（成功扫描后）
            if self.api_limit_errors > 0 and new_pairs_found > 0:
                self.logger.info("✅ API限制错误计数重置")
                self.api_limit_errors = 0
            
            if new_pairs_found > 0:
                self.logger.info(f"✅ 多工厂扫描完成: 发现 {new_pairs_found} 个新交易对")
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
    
    async def _get_factory_contracts(self):
        """🎯 修改：获取多个工厂合约实例"""
        # 🎯 新增：限制状态检查
        if self.is_limit_reached:
            self.logger.debug("⏭️ 达到每日限制，跳过合约获取")
            return []
            
        try:
            if not self.node_manager.http_nodes:
                self.logger.error("❌ 没有可用的HTTP节点")
                return []

            healthy_nodes = [node for node in self.node_manager.http_nodes 
                            if node.get('healthy', True)]
            
            if not healthy_nodes:
                self.logger.error("❌ 所有HTTP节点都不可用")
                return []

            # 选择第一个健康节点
            node = healthy_nodes[0]
            w3_instance = node['w3']
            
            # 🎯 修改：监听2个主要工厂合约（PancakeSwap V1和V2）
            factory_configs = [
                {
                    'name': 'PancakeSwap V2',
                    'address': Web3.to_checksum_address('0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73'),
                    'abi': self.config.PANCAKE_FACTORY_ABI
                },
                {
                    'name': 'PancakeSwap V1', 
                    'address': Web3.to_checksum_address('0xBCfCcbde45cE874adCB698cC183deBcF17952812'),
                    'abi': self.config.PANCAKE_FACTORY_ABI
                }
            ]
            
            factories = []
            for config in factory_configs:
                try:
                    contract = w3_instance.eth.contract(
                        address=config['address'],
                        abi=config['abi']
                    )
                    factories.append({
                        'name': config['name'],
                        'contract': contract
                    })
                    self.logger.info(f"✅ 成功初始化工厂合约: {config['name']}")
                except Exception as e:
                    self.logger.warning(f"初始化工厂合约失败 {config['name']}: {e}")
            
            self.logger.info(f"✅ 成功初始化 {len(factories)} 个工厂合约")
            return factories
            
        except Exception as e:
            self.logger.error(f"获取工厂合约失败: {e}")
            return []
    
    async def _process_new_token(self, token_address, pair_address):
        """处理新代币检测"""
        # 🎯 新增：限制状态检查
        if self.is_limit_reached:
            self.logger.debug(f"⏭️ 达到每日限制，跳过代币处理: {token_address}")
            return
            
        try:
            self.logger.info(f"🚨 处理新代币: {token_address}")
            await self._execute_detection_immediately(token_address, pair_address)
                
        except Exception as e:
            self.logger.error(f"代币处理失败 {token_address}: {e}")
    
    async def _execute_detection_immediately(self, token_address, pair_address):
        """立即执行代币检测 - 添加简单的流动性过滤"""
        # 🎯 新增：限制状态检查
        if self.is_limit_reached:
            self.logger.debug(f"⏭️ 达到每日限制，跳过代币检测: {token_address}")
            return
            
        try:
            from risk_detector import RiskDetector
            from notification_manager import NotificationManager
            
            # 🎯 修改：传递event_listener引用
            detector = RiskDetector(self.config, self.node_manager, self.cache_manager, self)
            notifier = NotificationManager(self.config, self)
            
            start_time = asyncio.get_event_loop().time()
            
            risk_report = await detector.detect_risks(token_address, pair_address)
            detection_time = asyncio.get_event_loop().time() - start_time
            
            self.logger.info(f"✅ 代币检测完成: {token_address}, 耗时: {detection_time:.2f}秒")
            
            # ✅ 新增：简单的流动性锁定过滤
            liquidity_info = risk_report['risks'].get('liquidity_lock', {})
            if not liquidity_info.get('locked', False):
                self.logger.info(f"🦺 跳过未锁定流动性的代币: {token_address}")
                return
            
            # 发送通知
            await notifier.send_dingtalk_notification(risk_report, detection_time)
            
        except Exception as e:
            self.logger.error(f"代币检测流程失败 {token_address}: {e}")
    
    async def _can_make_request(self):
        """检查是否可以进行API调用"""
        # 🎯 新增：限制状态检查
        if self.is_limit_reached:
            return False
        return True
    
    def get_system_status(self):
        """🎯 新增：获取系统状态信息"""
        status = {
            "is_running": self.is_running,
            "scan_count_today": self.scan_count_today,
            "daily_scan_limit": self.daily_scan_limit,
            "is_limit_reached": self.is_limit_reached,
            "last_reset_time": self.last_reset_time,
            "processed_blocks_count": len(self.processed_blocks),
            "api_limit_errors": self.api_limit_errors
        }
        
        if self.is_limit_reached:
            status["status"] = "limited"
            status["message"] = f"今日扫描已达上限 ({self.scan_count_today}/{self.daily_scan_limit})"
        else:
            status["status"] = "active"
            status["message"] = f"运行中 ({self.scan_count_today}/{self.daily_scan_limit})"
            
        return status
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("事件监听器已停止")
