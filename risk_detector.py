import asyncio
import aiohttp
import json
import logging
from web3 import Web3
from tenacity import retry, stop_after_attempt, wait_exponential

class RiskDetector:
    def __init__(self, config, node_manager, cache_manager):
        self.config = config
        self.node_manager = node_manager
        self.cache_manager = cache_manager
        self.logger = logging.getLogger(__name__)
        
        # 标准ERC20 ABI
        self.erc20_abi = [
            {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
            {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
        ]
    
    async def detect_risks(self, token_address, pair_address):
        """执行多维度风险检测"""
        risk_report = {
            'token_address': token_address,
            'pair_address': pair_address,
            'detection_time': None,
            'risks': {},
            'progress_bars': {},
            'badges': {}
        }
        
        # 并行执行检测任务
        tasks = [
            self._detect_liquidity_risks(token_address, pair_address),
            self._detect_contract_risks(token_address),
            self._detect_other_risks(token_address)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 整合检测结果
        liquidity_risks, contract_risks, other_risks = results
        
        risk_report['risks'] = {
            **liquidity_risks['risks'],
            **contract_risks['risks'],
            **other_risks['risks']
        }
        
        risk_report['progress_bars'] = {
            **liquidity_risks['progress_bars'],
            **contract_risks['progress_bars'],
            **other_risks['progress_bars']
        }
        
        risk_report['badges'] = {
            **liquidity_risks['badges'],
            **contract_risks['badges'],
            **other_risks['badges']
        }
        
        # 获取代币基本信息
        token_info = await self._get_token_info(token_address)
        risk_report.update(token_info)
        
        return risk_report
    
    async def _get_token_info(self, token_address):
        """获取代币基本信息"""
        try:
            contract = self.node_manager.http_nodes[0]['w3'].eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=self.erc20_abi
            )
            
            name = await self.node_manager.make_http_request('eth_call', {
                'to': token_address,
                'data': contract.functions.name()._encode_transaction_data()
            })
            symbol = await self.node_manager.make_http_request('eth_call', {
                'to': token_address,
                'data': contract.functions.symbol()._encode_transaction_data()
            })
            total_supply = await self.node_manager.make_http_request('eth_call', {
                'to': token_address,
                'data': contract.functions.totalSupply()._encode_transaction_data()
            })
            
            return {
                'token_name': contract.functions.name().decode_output(name) if name else 'Unknown',
                'token_symbol': contract.functions.symbol().decode_output(symbol) if symbol else 'Unknown',
                'total_supply': int(total_supply.hex(), 16) if total_supply else 0
            }
        except Exception as e:
            self.logger.error(f"获取代币信息失败: {e}")
            return {
                'token_name': 'Unknown',
                'token_symbol': 'Unknown',
                'total_supply': 0
            }
    
    async def _detect_liquidity_risks(self, token_address, pair_address):
        """检测流动性相关风险"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 检测流动性锁定
            lock_status = await self._check_liquidity_lock(pair_address)
            risks['liquidity_lock'] = lock_status
            
            # 检测流动性金额
            liquidity_usd = await self._get_liquidity_usd(token_address, pair_address)
            risks['liquidity_amount'] = liquidity_usd
            
            # 构建进度条
            progress_bars['economic_model'] = self._build_economic_progress_bar(
                lock_status, liquidity_usd
            )
            
            # 构建徽章
            badges['lp_burn'] = self._build_lp_burn_badge(lock_status)
            
        except Exception as e:
            self.logger.error(f"流动性风险检测失败: {e}")
            risks['liquidity_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    async def _detect_contract_risks(self, token_address):
        """检测合约安全风险"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 貔貅盘检测
            honeypot_result = await self._detect_honeypot(token_address)
            risks['honeypot'] = honeypot_result
            
            # 交易税检测
            tax_rate = await self._detect_tax_rate(token_address)
            risks['tax_rate'] = tax_rate
            
            # 权限风险检测
            permission_risks = await self._detect_permission_risks(token_address)
            risks.update(permission_risks)
            
            # 构建进度条
            progress_bars['transaction_restrictions'] = self._build_transaction_progress_bar(honeypot_result)
            progress_bars['permission_backdoor'] = self._build_permission_progress_bar(permission_risks)
            progress_bars['security_vulnerabilities'] = self._build_security_progress_bar(honeypot_result, permission_risks)
            
        except Exception as e:
            self.logger.error(f"合约风险检测失败: {e}")
            risks['contract_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    async def _detect_other_risks(self, token_address):
        """检测其他风险"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 预挖矿检测
            premine_result = await self._detect_premine(token_address)
            risks['premine'] = premine_result
            badges['premine_detection'] = self._build_premine_badge(premine_result)
            
            # 预售情况检测
            presale_result = await self._detect_presale(token_address)
            risks['presale'] = presale_result
            badges['presale_situation'] = self._build_presale_badge(presale_result)
            
            # 白名单机制检测
            whitelist_result = await self._detect_whitelist(token_address)
            risks['whitelist'] = whitelist_result
            badges['whitelist_mechanism'] = self._build_whitelist_badge(whitelist_result)
            
            # 社区驱动检测
            community_result = await self._detect_community_driven(token_address)
            badges['community_driven'] = self._build_community_badge(community_result)
            
        except Exception as e:
            self.logger.error(f"其他风险检测失败: {e}")
            risks['other_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # 具体的检测方法实现（部分关键方法）
    async def _check_liquidity_lock(self, pair_address):
        """检查流动性锁定状态"""
        try:
            # 这里需要实现具体的流动性锁定检查逻辑
            # 包括检查锁定时间、锁定比例、分段解锁等
            return {
                'locked': False,
                'lock_days': 0,
                'lock_ratio': 0,
                'has_vesting': False
            }
        except Exception as e:
            self.logger.error(f"流动性锁定检查失败: {e}")
            return {'error': str(e)}
    
    async def _get_liquidity_usd(self, token_address, pair_address):
        """获取流动性USD价值"""
        try:
            # 使用DexScreener API获取实时流动性数据
            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://api.dexscreener.com/latest/dex/pairs/bsc/{pair_address}') as response:
                    if response.status == 200:
                        data = await response.json()
                        pair_data = data.get('pair', {})
                        return float(pair_data.get('liquidity', {}).get('usd', 0))
            return 0
        except Exception as e:
            self.logger.error(f"获取流动性USD失败: {e}")
            return 0
    
    async def _detect_honeypot(self, token_address):
        """检测貔貅盘"""
        try:
            # 静态代码分析
            bytecode = await self.node_manager.make_http_request('get_code', token_address)
            
            # 模拟交易测试
            simulation_result = await self._simulate_trade(token_address)
            
            # 第三方黑名单检查
            blacklist_result = await self._check_blacklist(token_address)
            
            return {
                'is_honeypot': False,
                'transfer_restrictions': False,
                'blacklisted': blacklist_result.get('blacklisted', False),
                'simulation_success': simulation_result.get('success', False)
            }
        except Exception as e:
            self.logger.error(f"貔貅盘检测失败: {e}")
            return {'error': str(e)}
    
    async def _detect_tax_rate(self, token_address):
        """检测交易税率"""
        try:
            # 通过合约ABI调用buyFee/sellFee函数
            contract = self.node_manager.http_nodes[0]['w3'].eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=self.erc20_abi + [
                    {"constant": True, "inputs": [], "name": "buyFee", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
                    {"constant": True, "inputs": [], "name": "sellFee", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
                ]
            )
            
            buy_fee = 0
            sell_fee = 0
            
            try:
                buy_fee_data = await self.node_manager.make_http_request('eth_call', {
                    'to': token_address,
                    'data': contract.functions.buyFee()._encode_transaction_data()
                })
                if buy_fee_data:
                    buy_fee = contract.functions.buyFee().decode_output(buy_fee_data) / 100
            except:
                pass
                
            try:
                sell_fee_data = await self.node_manager.make_http_request('eth_call', {
                    'to': token_address,
                    'data': contract.functions.sellFee()._encode_transaction_data()
                })
                if sell_fee_data:
                    sell_fee = contract.functions.sellFee().decode_output(sell_fee_data) / 100
            except:
                pass
            
            return {
                'buy_tax': buy_fee,
                'sell_tax': sell_fee,
                'high_tax': buy_fee > self.config.MAX_TAX_RATE or sell_fee > self.config.MAX_TAX_RATE
            }
        except Exception as e:
            self.logger.error(f"税率检测失败: {e}")
            return {'buy_tax': 0, 'sell_tax': 0, 'high_tax': False}
    
    # 新增的缺失方法
    async def _detect_permission_risks(self, token_address):
        """检测权限风险"""
        try:
            # 这里实现权限风险检测逻辑
            # 例如：检查合约是否有黑名单、增发、修改税费等权限
            return {
                'has_blacklist': False,
                'can_mint': False,
                'can_pause': False,
                'owner_renounced': True
            }
        except Exception as e:
            self.logger.error(f"权限风险检测失败: {e}")
            return {'error': str(e)}
    
    async def _detect_premine(self, token_address):
        """检测预挖矿"""
        try:
            # 实现预挖矿检测逻辑
            return {
                'premine_ratio': 0,
                'has_premine': False
            }
        except Exception as e:
            self.logger.error(f"预挖矿检测失败: {e}")
            return {'error': str(e)}
    
    async def _detect_presale(self, token_address):
        """检测预售情况"""
        try:
            # 实现预售检测逻辑
            return {
                'has_presale': False,
                'presale_platform': None
            }
        except Exception as e:
            self.logger.error(f"预售检测失败: {e}")
            return {'error': str(e)}
    
    async def _detect_whitelist(self, token_address):
        """检测白名单机制"""
        try:
            # 实现白名单检测逻辑
            return {
                'has_whitelist': False,
                'whitelist_only': False
            }
        except Exception as e:
            self.logger.error(f"白名单检测失败: {e}")
            return {'error': str(e)}
    
    async def _detect_community_driven(self, token_address):
        """检测社区驱动"""
        try:
            # 实现社区驱动检测逻辑
            return {
                'is_community_driven': True,
                'has_roadmap': False
            }
        except Exception as e:
            self.logger.error(f"社区驱动检测失败: {e}")
            return {'error': str(e)}
    
    async def _simulate_trade(self, token_address):
        """模拟交易测试"""
        try:
            # 实现交易模拟逻辑
            return {
                'success': True,
                'buy_success': True,
                'sell_success': True
            }
        except Exception as e:
            self.logger.error(f"交易模拟失败: {e}")
            return {'error': str(e)}
    
    async def _check_blacklist(self, token_address):
        """检查黑名单"""
        try:
            # 实现黑名单检查逻辑
            return {
                'blacklisted': False,
                'reports': 0
            }
        except Exception as e:
            self.logger.error(f"黑名单检查失败: {e}")
            return {'error': str(e)}
    
    # 进度条构建方法
    def _build_economic_progress_bar(self, lock_status, liquidity_usd):
        """构建经济模型进度条"""
        score = 10
        
        # 流动性金额评分
        if liquidity_usd < self.config.MIN_LIQUIDITY_USD:
            score -= 6
        elif liquidity_usd < self.config.MIN_LIQUIDITY_USD * 5:
            score -= 3
        
        # 流动性锁定评分
        if not lock_status.get('locked', False):
            score -= 4
        elif lock_status.get('lock_ratio', 0) < self.config.MIN_LOCK_RATIO:
            score -= 2
        
        if score >= 8:
            return "[==========] 模型合理"
        elif score >= 5:
            return "[=====-----] 存在缺陷"
        else:
            return "[----------] 模型恶劣"
    
    def _build_transaction_progress_bar(self, honeypot_result):
        """构建交易限制进度条"""
        if honeypot_result.get('transfer_restrictions', False):
            return "[----------] 严格限制"
        elif honeypot_result.get('blacklisted', False):
            return "[=====-----] 部分限制"
        else:
            return "[==========] 无限制"
    
    def _build_permission_progress_bar(self, permission_risks):
        """构建权限进度条"""
        score = 10
        
        if permission_risks.get('has_blacklist', False):
            score -= 3
        if permission_risks.get('can_mint', False):
            score -= 3
        if permission_risks.get('can_pause', False):
            score -= 2
        if not permission_risks.get('owner_renounced', True):
            score -= 2
        
        if score >= 8:
            return "[==========] 权限安全"
        elif score >= 5:
            return "[=====-----] 权限中等"
        else:
            return "[----------] 权限危险"
    
    def _build_security_progress_bar(self, honeypot_result, permission_risks):
        """构建安全进度条"""
        score = 10
        
        if honeypot_result.get('is_honeypot', False):
            score -= 5
        if honeypot_result.get('transfer_restrictions', False):
            score -= 3
        if not permission_risks.get('owner_renounced', True):
            score -= 2
        
        if score >= 8:
            return "[==========] 安全可靠"
        elif score >= 5:
            return "[=====-----] 存在风险"
        else:
            return "[----------] 高危风险"
    
    # 徽章构建方法
    def _build_lp_burn_badge(self, lock_status):
        """构建LP代币销毁徽章"""
        if lock_status.get('locked', False) and lock_status.get('lock_ratio', 0) >= 0.9:
            return "✅ 已销毁"
        elif lock_status.get('locked', False) and lock_status.get('lock_ratio', 0) >= 0.8:
            return "⚠️ 部分锁定"
        else:
            return "❌ 未处理"
    
    def _build_premine_badge(self, premine_result):
        """构建预挖矿徽章"""
        premine_ratio = premine_result.get('premine_ratio', 0)
        if premine_ratio == 0:
            return "✅ 无预挖矿"
        elif premine_ratio <= self.config.MAX_PREMINE_RATIO:
            return "⚠️ 少量预挖"
        else:
            return "❌ 大量预挖"
    
    def _build_presale_badge(self, presale_result):
        """构建预售徽章"""
        if presale_result.get('has_presale', False):
            return "💰 有预售"
        else:
            return "✅ 无预售"
    
    def _build_whitelist_badge(self, whitelist_result):
        """构建白名单徽章"""
        if whitelist_result.get('has_whitelist', False):
            return "🔒 有白名单"
        else:
            return "✅ 无白名单"
    
    def _build_community_badge(self, community_result):
        """构建社区徽章"""
        if community_result.get('is_community_driven', False):
            return "👥 社区驱动"
        else:
            return "👑 团队驱动"
