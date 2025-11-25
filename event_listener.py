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
        
        # 智能频率控制
        self.last_check_time = 0
        self.consecutive_checks = 0
        self._checking = False
        
        # 延迟初始化合约
        self.factory_contract = None
        
        # API配额管理
        self.daily_quota = 100000
        self.used_today = 0
        self.quota_reset_time = time.time()
        
        # ✅ 优化：更精细的API限制控制
        self.api_limit_errors = 0
        self.last_api_limit_time = 0
        self.current_node_index = 0  # 当前使用的节点索引
        self.node_blacklist = {}     # 节点黑名单（临时禁用）
    
    async def start_listening(self):
        """开始监听事件 - 保证8秒内检测到新代币"""
        self.is_running = True
        self.logger.info("开始监听BSC链上事件...")
        
        # 合约初始化（最多重试3次）
        max_retries = 3
        retry_count = 0
        
        while self.is_running and not self.factory_contract and retry_count < max_retries:
            await self._initialize_contract()
            if not self.factory_contract:
                retry_count += 1
                self.logger.warning(f"合约初始化失败，{retry_count}/{max_retries} 次重试，5秒后重试...")
                await asyncio.sleep(5)
        
        if not self.factory_contract:
            self.logger.error("合约初始化失败，无法开始监听")
            self.is_running = False
            return
        
        self.logger.info("✅ 合约初始化成功，开始监听新交易对...")
        
        # 等待一段时间再开始，避免启动风暴
        await asyncio.sleep(5)
        
        while self.is_running:
            try:
                ws_url = await self.node_manager.get_current_websocket_url()
                if not ws_url:
                    self.logger.warning("没有可用的WebSocket URL，等待10秒后重试...")
                    await asyncio.sleep(10)
                    continue
                    
                await self._listen_websocket(ws_url)
                
            except Exception as e:
                self.logger.error(f"WebSocket监听失败: {e}", exc_info=True)
                await asyncio.sleep(10)
    
    async def _initialize_contract(self):
        """合约初始化 - 多节点轮询"""
        try:
            if not self.node_manager.http_nodes:
                self.logger.error("❌ 没有可用的HTTP节点")
                return False

            healthy_nodes = [node for node in self.node_manager.http_nodes 
                            if node.get('healthy', True)]
            
            if not healthy_nodes:
                self.logger.error("❌ 所有HTTP节点都不可用")
                return False

            self.logger.info(f"🔍 尝试从 {len(healthy_nodes)} 个健康节点初始化合约")
            
            # 多节点轮询尝试
            for i, node in enumerate(healthy_nodes[:3]):
                try:
                    self.logger.info(f"尝试节点 {i+1}/{min(3, len(healthy_nodes))}: {node.get('name', '未知')}")
                    
                    w3_instance = node['w3']
                    self.factory_contract = w3_instance.eth.contract(
                        address=Web3.to_checksum_address(self.config.PANCAKE_FACTORY),
                        abi=self.config.PANCAKE_FACTORY_ABI
                    )
                    
                    # 测试合约可用性
                    pair_count = self.factory_contract.functions.allPairsLength().call()
                    self.logger.info(f"✅ 节点 {node.get('name', '未知')} 初始化成功，当前交易对数量: {pair_count}")
                    return True
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ 节点 {node.get('name', '未知')} 初始化失败: {str(e)[:100]}...")
                    node['healthy'] = False
                    continue

            self.logger.error("❌ 所有节点初始化尝试均失败")
            return False
            
        except Exception as e:
            self.logger.error(f"💥 合约初始化过程异常: {e}", exc_info=True)
            self.factory_contract = None
            return False
    
    async def _listen_websocket(self, ws_url):
        """WebSocket监听 - 进一步降低频率"""
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
                
                self.consecutive_checks = 0
                
                while self.is_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(message)
                        
                        if 'params' in data and data['params'].get('subscription'):
                            self.consecutive_checks += 1
                            
                            # ✅ 进一步降低频率
                            # 策略1：前3个块立即检查（保证启动时的及时性）
                            if self.consecutive_checks <= 3:
                                self.logger.info("🚀 启动检查：收到新块通知")
                                asyncio.create_task(self._check_recent_blocks_fast(1))
                            
                            # 策略2：正常运行时，每4个块检查一次（BSC出块时间约3秒，平均延迟6秒）
                            elif self.consecutive_checks % 4 == 0:
                                self.logger.info("🔍 实时检查：收到新块通知")
                                asyncio.create_task(self._check_recent_blocks_fast(1))
                            
                            # 策略3：每15个块做一次深度检查（补全可能遗漏的交易对）
                            elif self.consecutive_checks % 15 == 0:
                                self.logger.info("📊 深度检查：扫描最近区块")
                                asyncio.create_task(self._check_recent_blocks_safe(2))  # ✅ 修改：只扫描2个块
                            
                            else:
                                self.logger.debug("⏭️ 智能跳过：频率控制")
                                continue
                                
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                            self.logger.debug("发送心跳包")
                        except Exception:
                            self.logger.warning("心跳发送失败，重新连接...")
                            break
                    except Exception as e:
                        self.logger.error(f"WebSocket接收错误: {e}", exc_info=True)
                        break
                        
        except Exception as e:
            self.logger.error(f"WebSocket连接失败 {ws_url}: {e}", exc_info=True)
            self.node_manager.mark_websocket_unhealthy(ws_url)
    
    async def _check_recent_blocks_fast(self, block_range=1):
        """✅ 新增：快速检查方法 - 保证8秒内检测"""
        # 前置检查
        if not await self._can_make_request():
            return
        
        if not self.factory_contract:
            return

        # API限制冷却检查
        current_time = time.time()
        if self.api_limit_errors > 0 and current_time - self.last_api_limit_time < 10:  # 快速检查冷却时间较短
            self.logger.debug("⏸️ 快速检查冷却中，跳过本次检查")
            return

        try:
            # 获取最新区块
            latest_block = await self.node_manager.make_http_request('get_block', 'latest')
            if not latest_block:
                return
                
            block_number = latest_block.number
            
            # 快速扫描：只扫描最新1个块
            from_block = block_number  # ✅ 修改：只扫描最新1个块
            to_block = block_number
            self.logger.info(f"🚀 快速扫描: 区块 {from_block}-{to_block}")
            
            # 使用专门的快速扫描方法
            await self._scan_blocks_fast(from_block, to_block)
            
            await self._record_request()
                
        except Exception as e:
            self.logger.error(f"快速检查失败: {e}")
    
    async def _check_recent_blocks_safe(self, block_range=2):
        """✅ 新增：安全检查方法 - 补全可能遗漏的交易对"""
        # 前置检查
        if not await self._can_make_request():
            return
        
        if not self.factory_contract:
            return

        # API限制冷却检查（安全检查冷却时间较长）
        current_time = time.time()
        if self.api_limit_errors > 0 and current_time - self.last_api_limit_time < 30:
            self.logger.warning("⏸️ 安全检查冷却中，跳过本次检查")
            return

        try:
            latest_block = await self.node_manager.make_http_request('get_block', 'latest')
            if not latest_block:
                return
                
            block_number = latest_block.number
            
            # 安全检查：扫描稍多区块，但避免触发限制
            last_deep_scan = self.cache_manager.get('system', 'last_deep_scan')
            if last_deep_scan is None:
                last_deep_scan = block_number - 20  # 初始回溯20个块
            
            from_block = max(last_deep_scan + 1, block_number - block_range)
            self.logger.info(f"📊 安全扫描: 区块 {from_block}-{block_number}")
            
            events_found = await self._scan_blocks_safe(from_block, block_number)
            
            if events_found > 0:
                self.cache_manager.set('system', 'last_deep_scan', block_number, 3600)
                    
            await self._record_request()
                
        except Exception as e:
            self.logger.error(f"安全检查失败: {e}")
    
    async def _scan_blocks_fast(self, from_block, to_block):
        """✅ 新增：快速扫描方法 - 最小化API调用"""
        try:
            if from_block > to_block:
                from_block, to_block = to_block, from_block
            
            # 快速扫描：严格限制范围
            max_block_range = 1  # ✅ 修改：快速扫描最多1个块
            if to_block - from_block > max_block_range:
                to_block = from_block + max_block_range
                self.logger.warning(f"⚠️ 快速扫描范围过大，调整为: {from_block}-{to_block}")
            
            loop = asyncio.get_event_loop()
            events = await loop.run_in_executor(
                None,
                lambda: self.factory_contract.events.PairCreated.get_logs(
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
                self.logger.info(f"✅ 快速扫描完成: 发现 {new_pairs_found} 个新交易对")
            else:
                self.logger.debug(f"快速扫描完成: 区块 {from_block}-{to_block} 无新交易对")
                
            return new_pairs_found
            
        except Exception as e:
            error_msg = str(e)
            
            # API限制特殊处理
            if 'limit exceeded' in error_msg or 'rate limit' in error_msg or '32005' in error_msg:
                self.api_limit_errors += 1
                self.last_api_limit_time = time.time()
                
                # 快速检查遇到限制：短暂暂停
                if self.api_limit_errors == 1:
                    self.logger.warning("⚠️ 快速检查遇到API限制，暂停10秒")  # ✅ 修改：延长到10秒
                    await asyncio.sleep(10)
                else:
                    self.logger.warning("⚠️ 快速检查频繁遇到限制，暂停20秒")  # ✅ 修改：延长到20秒
                    await asyncio.sleep(20)
            
            self.logger.error(f"快速扫描失败 {from_block}-{to_block}: {e}")
            return 0
    
    async def _scan_blocks_safe(self, from_block, to_block):
        """✅ 新增：安全扫描方法 - 更保守的策略"""
        try:
            if from_block > to_block:
                from_block, to_block = to_block, from_block
            
            # 安全扫描：更严格的范围限制
            max_block_range = 2  # ✅ 修改：安全扫描最多2个块
            if to_block - from_block > max_block_range:
                to_block = from_block + max_block_range
                self.logger.warning(f"⚠️ 安全扫描范围过大，调整为: {from_block}-{to_block}")
            
            loop = asyncio.get_event_loop()
            events = await loop.run_in_executor(
                None,
                lambda: self.factory_contract.events.PairCreated.get_logs(
                    fromBlock=from_block,
                    toBlock=to_block
                )
            )
            
            new_pairs_found = 0
            for event in events:
                token_address = event.args.token0
                pair_address = event.args.pair
                
                cache_key = f"pair_{pair_address}"
                if self.cache_manager.exists('detected_pairs', cache_key):
                    continue
                
                self.logger.info(f"🎯 深度检查发现新交易对: {token_address} -> {pair_address}")
                
                self.cache_manager.set('detected_pairs', cache_key, True, 3600)
                await self._process_new_token(token_address, pair_address)
                new_pairs_found += 1
            
            self.logger.info(f"📊 安全扫描完成: 在区块 {from_block}-{to_block} 中发现 {new_pairs_found} 个新交易对")
            return new_pairs_found
            
        except Exception as e:
            error_msg = str(e)
            
            # API限制特殊处理
            if 'limit exceeded' in error_msg or 'rate limit' in error_msg or '32005' in error_msg:
                self.api_limit_errors += 1
                self.last_api_limit_time = time.time()
                
                self.logger.warning("⚠️ 安全扫描遇到API限制，暂停30秒")  # ✅ 修改：延长到30秒
                await asyncio.sleep(30)
            
            self.logger.error(f"安全扫描失败 {from_block}-{to_block}: {e}")
            return 0
    
    async def _process_new_token(self, token_address, pair_address):
        """处理新代币检测 - 保证快速通知"""
        try:
            # ✅ 立即处理，不计算优先级（保证速度）
            self.logger.info(f"🚨 立即处理新代币: {token_address}")
            await self._execute_detection_immediately(token_address, pair_address)
                
        except Exception as e:
            self.logger.error(f"代币处理失败 {token_address}: {e}", exc_info=True)
    
    async def _execute_detection_immediately(self, token_address, pair_address):
        """立即执行代币检测 - 优化性能"""
        try:
            from risk_detector import RiskDetector
            from notification_manager import NotificationManager
            
            detector = RiskDetector(self.config, self.node_manager, self.cache_manager)
            
            start_time = asyncio.get_event_loop().time()
            
            # ✅ 优化：只执行关键检测，保证速度
            risk_report = await detector.detect_risks(token_address, pair_address)
            detection_time = asyncio.get_event_loop().time() - start_time
            
            self.logger.info(f"✅ 代币检测完成: {token_address}, 耗时: {detection_time:.2f}秒")
            
            # 发送通知
            notifier = NotificationManager(self.config)
            await notifier.send_dingtalk_notification(risk_report, detection_time)
            
        except Exception as e:
            self.logger.error(f"代币检测流程失败 {token_address}: {e}", exc_info=True)
    
    async def _can_make_request(self):
        """检查是否可以进行API调用"""
        current_time = time.time()
        if current_time - self.quota_reset_time > 86400:
            self.used_today = 0
            self.quota_reset_time = current_time
        
        if self.used_today >= self.daily_quota * 0.9:
            self.logger.warning("⚠️ API配额接近限制，进入节流模式")
            return False
        return True
    
    async def _record_request(self):
        """记录API调用"""
        self.used_today += 1
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("事件监听器已停止")
