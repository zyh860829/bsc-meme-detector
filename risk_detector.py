import asyncio
import aiohttp
import json
import logging
import time
from web3 import Web3
from tenacity import retry, stop_after_attempt, wait_exponential

class RiskDetector:
    def __init__(self, config, node_manager, cache_manager, event_listener=None):  # 🎯 新增：接收event_listener引用
        self.config = config
        self.node_manager = node_manager
        self.cache_manager = cache_manager
        self.event_listener = event_listener  # 🎯 新增：事件监听器引用
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
        """🎯 修改：添加限制检查的风险检测"""
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            self.logger.info(f"⏭️ 达到每日限制，跳过风险检测: {token_address}")
            return {
                'token_address': token_address,
                'pair_address': pair_address,
                'status': 'skipped',
                'reason': 'daily_limit_reached',
                'detection_time': 0,
                'risks': {},
                'progress_bars': {},
                'badges': {}
            }
        
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
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            return {
                'token_name': 'Unknown (limit reached)',
                'token_symbol': 'Unknown (limit reached)', 
                'total_supply': 0
            }
            
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
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            return {'risks': {}, 'progress_bars': {}, 'badges': {}}
            
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
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            return {'risks': {}, 'progress_bars': {}, 'badges': {}}
            
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
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            return {'risks': {}, 'progress_bars': {}, 'badges': {}}
            
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

    def _is_daily_limit_reached(self):
        """🎯 新增：检查是否达到每日限制"""
        if self.event_listener and hasattr(self.event_listener, 'is_limit_reached'):
            return self.event_listener.is_limit_reached
        return False

    # 其余方法保持不变...
    async def _check_liquidity_lock(self, pair_address):
        """修复：真正的流动性锁定检查"""
        try:
            # 使用DexScreener API检查锁定状态
            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://api.dexscreener.com/latest/dex/pairs/bsc/{pair_address}') as response:
                    if response.status == 200:
                        data = await response.json()
                        pair_info = data.get('pair', {})
                        
                        # 检查锁定信息
                        locked = pair_info.get('liquidity', {}).get('locked', False)
                        lock_info = pair_info.get('lockInfo', {})
                        lock_days = lock_info.get('lockDays', 0)
                        
                        return {
                            'locked': locked,
                            'lock_days': lock_days,
                            'lock_ratio': 0,  # 简化处理
                            'has_vesting': False,  # 简化处理
                            'risk_level': '低风险' if locked and lock_days >= 30 else '高风险'
                        }
            return {'locked': False, 'lock_days': 0, 'risk_level': '极高风险'}
        except Exception as e:
            self.logger.error(f"流动性锁定检查失败: {e}")
            return {'locked': False, 'lock_days': 0, 'risk_level': '未知'}

    # ... 其余方法保持不变
