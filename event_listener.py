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
        self.min_scan_interval = 30
        self.scan_count_today = 0
        self.daily_scan_limit = 500
        self.last_reset_time = time.time()
        
        # API限制管理
        self.api_limit_errors = 0
        self.last_api_limit_time = 0
        self.consecutive_checks = 0
        
        # ✅ 区块去重机制
        self.processed_blocks = set()
        self.last_block_number = 0
        self.max_processed_blocks = 1000
        
        # ✅ 新增：网络状况监控
        self.network_delay_history = []
        self.max_delay_history = 10
        
    async def start_listening(self):
        """开始监听事件"""
        self.is_running = True
        self.logger.info("🚀 启动智能动态过滤监听模式...")
        
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
        """🐢 超安全监听模式"""
        try:
            async with connect(ws_url) as ws:
                self.logger.info(f"✅ 成功连接到WebSocket: {ws_url}")
                
                subscription_message = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["newHeads"]
                }
                await ws.send(json.dumps(subscription_message))
                
                response = await ws.recv()
                self.logger.info(f"📨 订阅响应: {response}")
                
                self.consecutive_checks = 0
                self.last_scan_time = 0
                
                while self.is_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=60)
                        data = json.loads(message)
                        
                        if 'params' in data and data['params'].get('subscription'):
                            block_data = data['params']['result']
                            block_number_hex = block_data.get('number')
                            if not block_number_hex:
                                continue
                                
                            block_number = int(block_number_hex, 16)
                            
                            if block_number <= self.last_block_number:
                                self.logger.debug(f"⏭️ 跳过旧区块: {block_number}")
                                continue
                                
                            if block_number in self.processed_blocks:
                                self.logger.debug(f"⏭️ 区块 {block_number} 已处理过，跳过")
                                continue
                            
                            self.consecutive_checks += 1
                            current_time = time.time()
                            
                            if self._exceeded_daily_limit():
                                self.logger.warning("📊 达到每日扫描限制，跳过检查")
                                continue
                            
                            if current_time - self.last_scan_time < self.min_scan_interval:
                                wait_time = self.min_scan_interval - (current_time - self.last_scan_time)
                                self.logger.debug(f"⏰ 时间间隔限制，还需等待{wait_time:.1f}秒")
                                continue
                            
                            if self.api_limit_errors > 0 and current_time - self.last_api_limit_time < 60:
                                remaining = 60 - (current_time - self.last_api_limit_time)
                                self.logger.debug(f"❄️ API限制冷却中，还需等待{remaining:.1f}秒")
                                continue
                            
                            if self.consecutive_checks % 10 == 0:
                                self.logger.info("🔍 低频检查：收到新块通知")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                
                                self.last_block_number = block_number
                                self.processed_blocks.add(block_number)
                                self._clean_old_blocks()
                                
                                asyncio.create_task(self._ultra_safe_scan(block_number))
                            
                            elif self.consecutive_checks % 60 == 0:
                                self.logger.info("📊 超低频深度检查")
                                self.last_scan_time = current_time
                                self.scan_count_today += 1
                                
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
        """清理旧的区块记录"""
        if len(self.processed_blocks) > self.max_processed_blocks:
            blocks_to_remove = sorted(self.processed_blocks)[:self.max_processed_blocks // 2]
            for block in blocks_to_remove:
                self.processed_blocks.remove(block)
            self.logger.debug(f"🧹 清理了 {len(blocks_to_remove)} 个旧的区块记录")
    
    def _exceeded_daily_limit(self):
        """检查是否超过每日扫描限制"""
        current_time = time.time()
        if current_time - self.last_reset_time > 86400:
            self.scan_count_today = 0
            self.last_reset_time = current_time
            self.processed_blocks.clear()
            self.logger.info("🔄 每日扫描计数器已重置")
        
        if self.scan_count_today >= self.daily_scan_limit:
            return True
        return False
    
    async def _ultra_safe_scan(self, block_number):
        """🐢 超安全扫描方法"""
        if not await self._can_make_request():
            return

        try:
            self.logger.info(f"🐢 超安全扫描: 区块 {block_number} (今日扫描: {self.scan_count_today}/{self.daily_scan_limit})")
            await self._scan_blocks_ultra_safe(block_number, block_number)
                
        except Exception as e:
            self.logger.error(f"超安全扫描失败: {e}")
    
    async def _scan_blocks_ultra_safe(self, from_block, to_block):
        """🐢 超安全扫描"""
        try:
            if from_block > to_block:
                from_block, to_block = to_block, from_block
            
            max_block_range = 1
            if to_block - from_block > max_block_range:
                to_block = from_block + max_block_range
                self.logger.warning(f"⚠️ 扫描范围过大，调整为: {from_block}-{to_block}")
            
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
            
            if 'limit exceeded' in error_msg or 'rate limit' in error_msg or '32005' in error_msg:
                self.api_limit_errors += 1
                self.last_api_limit_time = time.time()
                
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
            await self._execute_detection_with_smart_filter(token_address, pair_address)
                
        except Exception as e:
            self.logger.error(f"代币处理失败 {token_address}: {e}")
    
    async def _execute_detection_with_smart_filter(self, token_address, pair_address):
        """✅ 新增：智能动态过滤检测"""
        try:
            from risk_detector import RiskDetector
            from notification_manager import NotificationManager
            
            # ✅ 第一步：评估网络状况并选择过滤级别
            filter_level = await self._determine_filter_level()
            self.logger.info(f"🎯 当前过滤级别: {filter_level}")
            
            detector = RiskDetector(self.config, self.node_manager, self.cache_manager)
            
            start_time = asyncio.get_event_loop().time()
            
            # ✅ 第二步：根据过滤级别执行相应深度的检测
            risk_report = await detector.detect_risks_with_level(token_address, pair_address, filter_level)
            detection_time = asyncio.get_event_loop().time() - start_time
            
            # ✅ 第三步：更新网络延迟历史
            self._update_network_delay(detection_time)
            
            self.logger.info(f"✅ {filter_level}检测完成: {token_address}, 耗时: {detection_time:.2f}秒")
            
            # ✅ 第四步：根据过滤级别执行相应的安全检查
            should_alert = await self._should_alert_by_level(risk_report, token_address, filter_level)
            if not should_alert:
                self.logger.info(f"🦺 {filter_level}过滤跳过: {token_address}")
                return
            
            # 发送通知（包含过滤级别信息）
            notifier = NotificationManager(self.config)
            await notifier.send_dingtalk_notification(risk_report, detection_time, filter_level)
            
        except Exception as e:
            self.logger.error(f"智能过滤检测失败 {token_address}: {e}")
    
    async def _determine_filter_level(self):
        """✅ 新增：根据网络状况确定过滤级别"""
        if not self.network_delay_history:
            return "balanced"  # 默认平衡级别
        
        avg_delay = sum(self.network_delay_history) / len(self.network_delay_history)
        
        if avg_delay <= self.config.NETWORK_EXCELLENT_THRESHOLD:
            return "comprehensive"  # 网络极好：全面过滤
        elif avg_delay <= self.config.NETWORK_GOOD_THRESHOLD:
            return "balanced"       # 网络良好：平衡过滤
        else:
            return "essential"      # 网络差：必要过滤
    
    def _update_network_delay(self, detection_time):
        """✅ 新增：更新网络延迟历史"""
        self.network_delay_history.append(detection_time)
        if len(self.network_delay_history) > self.max_delay_history:
            self.network_delay_history.pop(0)
    
    async def _should_alert_by_level(self, risk_report, token_address, filter_level):
        """✅ 新增：根据过滤级别执行相应的安全检查"""
        try:
            liquidity_info = risk_report['risks'].get('liquidity_lock', {})
            
            # 所有级别都检查的基本项目
            if not liquidity_info.get('locked', False):
                self.logger.info(f"🦺 过滤未锁定流动性的代币: {token_address}")
                return False
            
            honeypot_info = risk_report['risks'].get('honeypot', {})
            if honeypot_info.get('is_honeypot', False):
                self.logger.info(f"🦺 过滤检测到貔貅盘的代币: {token_address}")
                return False
            
            # 根据过滤级别增加额外检查
            if filter_level == "essential":
                # 必要级别：只做最基本检查
                return True
                
            elif filter_level == "balanced":
                # 平衡级别：增加交易税检查
                tax_info = risk_report['risks'].get('tax_rate', {})
                if tax_info.get('high_tax', False):
                    self.logger.info(f"🦺 平衡过滤：交易税过高 - {token_address}")
                    return False
                    
                # 平衡级别：检查锁定时间
                lock_days = liquidity_info.get('lock_days', 0)
                if lock_days < self.config.MIN_LOCK_DAYS:
                    self.logger.info(f"🦺 平衡过滤：锁定时间过短 - {token_address} ({lock_days}天)")
                    return False
                    
                return True
                
            elif filter_level == "comprehensive":
                # 全面级别：所有检查
                tax_info = risk_report['risks'].get('tax_rate', {})
                if tax_info.get('high_tax', False):
                    self.logger.info(f"🦺 全面过滤：交易税过高 - {token_address}")
                    return False
                    
                lock_days = liquidity_info.get('lock_days', 0)
                if lock_days < self.config.MIN_LOCK_DAYS:
                    self.logger.info(f"🦺 全面过滤：锁定时间过短 - {token_address} ({lock_days}天)")
                    return False
                    
                lp_age_minutes = liquidity_info.get('lp_age_minutes', 0)
                if lp_age_minutes < self.config.MIN_LP_AGE_MINUTES:
                    self.logger.info(f"🦺 全面过滤：LP池太新 - {token_address} ({lp_age_minutes}分钟)")
                    return False
                    
                risk_level = liquidity_info.get('risk_level', '极高风险')
                if risk_level in ['极高风险']:
                    self.logger.info(f"🦺 全面过滤：风险等级过高 - {token_address} ({risk_level})")
                    return False
                    
                return True
            
            return True
            
        except Exception as e:
            self.logger.error(f"级别安全检查失败 {token_address}: {e}")
            return False
    
    async def _can_make_request(self):
        """检查是否可以进行API调用"""
        return True
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("事件监听器已停止")
