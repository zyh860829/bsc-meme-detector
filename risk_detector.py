import asyncio
import aiohttp
import json
import logging
import time
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
    
    # ✅ 新增：分级检测方法
    async def detect_risks_with_level(self, token_address, pair_address, filter_level):
        """根据过滤级别执行相应深度的风险检测"""
        risk_report = {
            'token_address': token_address,
            'pair_address': pair_address,
            'filter_level': filter_level,
            'risks': {},
            'progress_bars': {},
            'badges': {}
        }
        
        # 根据过滤级别选择检测深度
        if filter_level == "essential":
            # 必要级别：只做最快的基础检测
            tasks = [
                self._detect_liquidity_risks_fast(token_address, pair_address),
                self._detect_contract_risks_fast(token_address)
            ]
        elif filter_level == "balanced":
            # 平衡级别：中等深度检测
            tasks = [
                self._detect_liquidity_risks_balanced(token_address, pair_address),
                self._detect_contract_risks_balanced(token_address),
                self._detect_other_risks_fast(token_address)
            ]
        else:  # comprehensive
            # 全面级别：完整深度检测
            tasks = [
                self._detect_liquidity_risks(token_address, pair_address),
                self._detect_contract_risks(token_address),
                self._detect_other_risks(token_address)
            ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 整合检测结果
        for result in results:
            if isinstance(result, dict):
                risk_report['risks'].update(result.get('risks', {}))
                risk_report['progress_bars'].update(result.get('progress_bars', {}))
                risk_report['badges'].update(result.get('badges', {}))
        
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
    
    # ✅ 新增：快速流动性风险检测
    async def _detect_liquidity_risks_fast(self, token_address, pair_address):
        """快速流动性风险检测 - 必要级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 只做最快的流动性锁定检查
            lock_status = await self._check_liquidity_lock_fast(pair_address)
            risks['liquidity_lock'] = lock_status
            
            # 快速获取流动性金额
            liquidity_usd = await self._get_liquidity_usd_fast(pair_address)
            risks['liquidity_amount'] = liquidity_usd
            
        except Exception as e:
            self.logger.error(f"快速流动性风险检测失败: {e}")
            risks['liquidity_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # ✅ 新增：平衡流动性风险检测
    async def _detect_liquidity_risks_balanced(self, token_address, pair_address):
        """平衡流动性风险检测 - 平衡级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 中等深度的流动性检查
            lock_status = await self._check_liquidity_lock_balanced(pair_address)
            risks['liquidity_lock'] = lock_status
            
            liquidity_usd = await self._get_liquidity_usd(token_address, pair_address)
            risks['liquidity_amount'] = liquidity_usd
            
            # 构建进度条
            progress_bars['economic_model'] = self._build_economic_progress_bar(lock_status, liquidity_usd)
            badges['lp_burn'] = self._build_lp_burn_badge(lock_status)
            
        except Exception as e:
            self.logger.error(f"平衡流动性风险检测失败: {e}")
            risks['liquidity_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    async def _detect_liquidity_risks(self, token_address, pair_address):
        """完整流动性风险检测 - 全面级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 完整的流动性检查
            lock_status = await self._check_liquidity_lock(pair_address)
            risks['liquidity_lock'] = lock_status
            
            liquidity_usd = await self._get_liquidity_usd(token_address, pair_address)
            risks['liquidity_amount'] = liquidity_usd
            
            progress_bars['economic_model'] = self._build_economic_progress_bar(lock_status, liquidity_usd)
            badges['lp_burn'] = self._build_lp_burn_badge(lock_status)
            
        except Exception as e:
            self.logger.error(f"流动性风险检测失败: {e}")
            risks['liquidity_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # ✅ 新增：快速合约风险检测
    async def _detect_contract_risks_fast(self, token_address):
        """快速合约风险检测 - 必要级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 只做最快的貔貅盘检测
            honeypot_result = await self._detect_honeypot_fast(token_address)
            risks['honeypot'] = honeypot_result
            
        except Exception as e:
            self.logger.error(f"快速合约风险检测失败: {e}")
            risks['contract_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # ✅ 新增：平衡合约风险检测
    async def _detect_contract_risks_balanced(self, token_address):
        """平衡合约风险检测 - 平衡级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            honeypot_result = await self._detect_honeypot(token_address)
            risks['honeypot'] = honeypot_result
            
            tax_rate = await self._detect_tax_rate(token_address)
            risks['tax_rate'] = tax_rate
            
            progress_bars['transaction_restrictions'] = self._build_transaction_progress_bar(honeypot_result)
            
        except Exception as e:
            self.logger.error(f"平衡合约风险检测失败: {e}")
            risks['contract_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    async def _detect_contract_risks(self, token_address):
        """完整合约风险检测 - 全面级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            honeypot_result = await self._detect_honeypot(token_address)
            risks['honeypot'] = honeypot_result
            
            tax_rate = await self._detect_tax_rate(token_address)
            risks['tax_rate'] = tax_rate
            
            permission_risks = await self._detect_permission_risks(token_address)
            risks.update(permission_risks)
            
            progress_bars['transaction_restrictions'] = self._build_transaction_progress_bar(honeypot_result)
            progress_bars['permission_backdoor'] = self._build_permission_progress_bar(permission_risks)
            progress_bars['security_vulnerabilities'] = self._build_security_progress_bar(honeypot_result, permission_risks)
            
        except Exception as e:
            self.logger.error(f"合约风险检测失败: {e}")
            risks['contract_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # ✅ 新增：快速其他风险检测
    async def _detect_other_risks_fast(self, token_address):
        """快速其他风险检测 - 平衡级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            # 快速预挖矿检测
            premine_result = await self._detect_premine_fast(token_address)
            risks['premine'] = premine_result
            badges['premine_detection'] = self._build_premine_badge(premine_result)
            
        except Exception as e:
            self.logger.error(f"快速其他风险检测失败: {e}")
            risks['other_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    async def _detect_other_risks(self, token_address):
        """完整其他风险检测 - 全面级别"""
        risks = {}
        progress_bars = {}
        badges = {}
        
        try:
            premine_result = await self._detect_premine(token_address)
            risks['premine'] = premine_result
            badges['premine_detection'] = self._build_premine_badge(premine_result)
            
            presale_result = await self._detect_presale(token_address)
            risks['presale'] = presale_result
            badges['presale_situation'] = self._build_presale_badge(presale_result)
            
            whitelist_result = await self._detect_whitelist(token_address)
            risks['whitelist'] = whitelist_result
            badges['whitelist_mechanism'] = self._build_whitelist_badge(whitelist_result)
            
            community_result = await self._detect_community_driven(token_address)
            badges['community_driven'] = self._build_community_badge(community_result)
            
        except Exception as e:
            self.logger.error(f"其他风险检测失败: {e}")
            risks['other_detection_failed'] = True
        
        return {'risks': risks, 'progress_bars': progress_bars, 'badges': badges}
    
    # 具体的检测方法实现
    async def _check_liquidity_lock_fast(self, pair_address):
        """快速流动性锁定检查 - 必要级别"""
        try:
            # 只使用DexScreener API快速检查
            dex_screener_lock = await self._check_dexscreener_lock(pair_address)
            
            return {
                'locked': dex_screener_lock.get('locked', False),
                'lock_days': dex_screener_lock.get('lock_days', 0),
                'risk_level': '未知'  # 快速检查不评估风险等级
            }
        except Exception as e:
            self.logger.error(f"快速流动性锁定检查失败: {e}")
            return {'locked': False}
    
    async def _check_liquidity_lock_balanced(self, pair_address):
        """平衡流动性锁定检查 - 平衡级别"""
        try:
            dex_screener_lock = await self._check_dexscreener_lock(pair_address)
            common_lock_contracts = await self._check_common_lock_contracts(pair_address)
            
            is_locked = (dex_screener_lock.get('locked', False) or 
                        common_lock_contracts.get('locked', False))
            
            lock_days = max(dex_screener_lock.get('lock_days', 0), 
                           common_lock_contracts.get('lock_days', 0))
            
            return {
                'locked': is_locked,
                'lock_days': lock_days,
                'risk_level': self._assess_liquidity_risk_simple(is_locked, lock_days)
            }
        except Exception as e:
            self.logger.error(f"平衡流动性锁定检查失败: {e}")
            return {'locked': False}
    
    async def _check_liquidity_lock(self, pair_address):
        """完整流动性锁定检查 - 全面级别"""
        try:
            dex_screener_lock = await self._check_dexscreener_lock(pair_address)
            common_lock_contracts = await self._check_common_lock_contracts(pair_address)
            lp_distribution = await self._check_lp_distribution(pair_address)
            lp_age = await self._get_lp_age(pair_address)
            
            is_locked = (dex_screener_lock.get('locked', False) or 
                        common_lock_contracts.get('locked', False))
            
            lock_days = max(dex_screener_lock.get('lock_days', 0), 
                           common_lock_contracts.get('lock_days', 0))
            
            return {
                'locked': is_locked,
                'lock_days': lock_days,
                'lock_ratio': lp_distribution.get('locked_ratio', 0),
                'has_vesting': common_lock_contracts.get('has_vesting', False),
                'lp_age_minutes': lp_age // 60,
                'risk_level': self._assess_liquidity_risk(is_locked, lock_days, lp_age)
            }
        except Exception as e:
            self.logger.error(f"流动性锁定检查失败: {e}")
            return {'error': str(e), 'locked': False}

    # 其他辅助方法保持不变，但可以添加快速版本...
    # 例如：_detect_honeypot_fast, _get_liquidity_usd_fast, _detect_premine_fast 等
    
    # 由于篇幅限制，这里只展示关键修改，其他方法保持原样
    # ...
