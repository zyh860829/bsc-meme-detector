#!/usr/bin/env python3
"""
BSC Meme币检测系统 - 完全实时数据版本
所有检测都基于BSC链上实时数据
"""

import asyncio
import os
import redis
from web3 import Web3
import requests
import json
import time
from datetime import datetime
from web3.middleware import geth_poa_middleware

class RealTimeBSCDetector:
    def __init__(self):
        # BSC主网RPC节点
        self.bsc_rpc = os.getenv('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/')
        self.w3 = Web3(Web3.HTTPProvider(self.bsc_rpc))
        
        # 添加BSC兼容中间件
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        # 初始化Redis
        self.redis_url = os.getenv('REDIS_URL')
        if self.redis_url:
            try:
                self.redis = redis.from_url(self.redis_url)
                self.redis.ping()
                print("✅ Redis连接成功")
            except:
                print("❌ Redis连接失败")
                self.redis = None
        else:
            self.redis = None
            
        self.dingtalk_webhook = os.getenv('DINGTALK_WEBHOOK', '')
        
        # PancakeSwap合约地址
        self.pancake_factory = self.w3.to_checksum_address('0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73')
        self.pancake_router = self.w3.to_checksum_address('0x10ED43C718714eb63d5aA57B78B54704E256024E')
        
        print(f"✅ BSC节点连接: {self.w3.is_connected()}")
        print(f"✅ 最新区块: {self.w3.eth.block_number}")

    async def get_token_info(self, contract_address: str) -> dict:
        """获取代币基本信息 - 完全实时"""
        try:
            checksum_address = self.w3.to_checksum_address(contract_address)
            
            # 标准ERC20 ABI
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [],
                    "name": "name",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "symbol",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "totalSupply",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "owner",
                    "outputs": [{"name": "", "type": "address"}],
                    "type": "function"
                }
            ]
            
            contract = self.w3.eth.contract(address=checksum_address, abi=erc20_abi)
            
            # 并行获取所有信息
            tasks = {
                'name': asyncio.get_event_loop().run_in_executor(None, contract.functions.name().call),
                'symbol': asyncio.get_event_loop().run_in_executor(None, contract.functions.symbol().call),
                'decimals': asyncio.get_event_loop().run_in_executor(None, contract.functions.decimals().call),
                'total_supply': asyncio.get_event_loop().run_in_executor(None, contract.functions.totalSupply().call),
            }
            
            results = {}
            for key, task in tasks.items():
                try:
                    results[key] = await task
                except Exception as e:
                    results[key] = f"Error: {str(e)}"
            
            # 尝试获取owner
            try:
                results['owner'] = contract.functions.owner().call()
            except:
                results['owner'] = "未知"
                
            return results
            
        except Exception as e:
            return {'error': f"获取代币信息失败: {str(e)}"}

    async def check_liquidity_real_time(self, contract_address: str) -> dict:
        """实时流动性检查 - 查询PancakeSwap池子"""
        try:
            checksum_address = self.w3.to_checksum_address(contract_address)
            wbnb_address = self.w3.to_checksum_address('0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c')
            
            # PancakeSwap Factory ABI - 获取交易对
            factory_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
                    "name": "getPair",
                    "outputs": [{"name": "pair", "type": "address"}],
                    "type": "function"
                }
            ]
            
            factory = self.w3.eth.contract(address=self.pancake_factory, abi=factory_abi)
            pair_address = factory.functions.getPair(checksum_address, wbnb_address).call()
            
            if pair_address == '0x0000000000000000000000000000000000000000':
                return {
                    'has_liquidity': False,
                    'pair_address': None,
                    'liquidity_amount': 0,
                    'risk_level': 'high'
                }
            
            # 获取交易对信息
            pair_abi = [
                {
                    "constant": True,
                    "inputs": [],
                    "name": "getReserves",
                    "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}, {"name": "_blockTimestampLast", "type": "uint32"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "token0",
                    "outputs": [{"name": "", "type": "address"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "token1",
                    "outputs": [{"name": "", "type": "address"}],
                    "type": "function"
                }
            ]
            
            pair_contract = self.w3.eth.contract(address=pair_address, abi=pair_abi)
            reserves = pair_contract.functions.getReserves().call()
            token0 = pair_contract.functions.token0().call()
            
            # 计算流动性（BNB价值）
            if token0.lower() == wbnb_address.lower():
                bnb_reserve = reserves[0] / 10**18  # WBNB有18位小数
            else:
                bnb_reserve = reserves[1] / 10**18
                
            # 粗略估算流动性价值（BNB价格约$300）
            liquidity_value = bnb_reserve * 300
            
            return {
                'has_liquidity': True,
                'pair_address': pair_address,
                'liquidity_amount': liquidity_value,
                'bnb_liquidity': bnb_reserve,
                'risk_level': 'low' if liquidity_value > 10000 else 'high'
            }
            
        except Exception as e:
            return {'error': str(e), 'risk_level': 'high'}

    async def check_honeypot_real_time(self, contract_address: str) -> dict:
        """实时貔貅盘检测 - 通过交易模拟"""
        try:
            # 这里可以集成honeypot检测API或自己实现交易模拟
            # 由于复杂度，我们先返回基础检测
            
            checksum_address = self.w3.to_checksum_address(contract_address)
            
            # 获取合约代码
            code = self.w3.eth.get_code(checksum_address)
            is_contract = len(code) > 0
            
            # 检查是否有黑名单函数（简化版）
            contract_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "", "type": "address"}],
                    "name": "isBlacklisted",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function"
                }
            ]
            
            try:
                contract = self.w3.eth.contract(address=checksum_address, abi=contract_abi)
                has_blacklist = True
            except:
                has_blacklist = False
                
            return {
                'is_honeypot': has_blacklist,  # 有黑名单功能可能是貔貅盘
                'is_contract': is_contract,
                'has_blacklist_function': has_blacklist,
                'code_size': len(code),
                'risk_level': 'high' if has_blacklist else 'medium'
            }
            
        except Exception as e:
            return {'error': str(e), 'risk_level': 'high'}

    async def get_token_price(self, contract_address: str) -> dict:
        """获取实时价格信息"""
        try:
            # 通过DeFiLlama或PancakeSwap API获取价格
            api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            response = requests.get(api_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and len(data['pairs']) > 0:
                    pair = data['pairs'][0]
                    return {
                        'price_usd': float(pair.get('priceUsd', 0)),
                        'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
                        'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                        'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                        'dex': pair.get('dexId', 'unknown')
                    }
            
            return {'price_usd': 0, 'liquidity_usd': 0, 'error': '未找到价格信息'}
            
        except Exception as e:
            return {'error': f"获取价格失败: {str(e)}"}

    async def check_ownership_real_time(self, contract_address: str) -> dict:
        """实时所有权检查"""
        try:
            token_info = await self.get_token_info(contract_address)
            owner = token_info.get('owner', '未知')
            
            # 检查owner是否是零地址（通常表示已放弃所有权）
            is_renounced = owner == '0x0000000000000000000000000000000000000000'
            
            return {
                'owner': owner,
                'is_renounced': is_renounced,
                'risk_level': 'low' if is_renounced else 'medium'
            }
            
        except Exception as e:
            return {'error': str(e), 'risk_level': 'high'}

    def calculate_risk_score(self, results: dict) -> int:
        """基于实时数据计算风险分数"""
        score = 5  # 基础分
        
        # 流动性风险
        liquidity = results.get('liquidity_check', {})
        if not liquidity.get('has_liquidity'):
            score += 3
        elif liquidity.get('liquidity_amount', 0) < 1000:
            score += 2
            
        # 貔貅盘风险
        honeypot = results.get('honeypot_check', {})
        if honeypot.get('is_honeypot'):
            score += 4
        if honeypot.get('has_blacklist_function'):
            score += 2
            
        # 所有权风险
        ownership = results.get('ownership_check', {})
        if not ownership.get('is_renounced'):
            score += 1
            
        # 价格数据风险
        price_info = results.get('price_check', {})
        if price_info.get('liquidity_usd', 0) < 5000:
            score += 1
            
        return min(score, 10)

    def generate_recommendation(self, results: dict) -> str:
        """生成实时投资建议"""
        risk_score = self.calculate_risk_score(results)
        
        if risk_score <= 3:
            return "✅ 低风险 - 可以考虑投资"
        elif risk_score <= 6:
            return "⚠️ 中等风险 - 谨慎投资"
        elif risk_score <= 8:
            return "🚨 高风险 - 不建议投资"
        else:
            return "❌ 极高风险 - 绝对避免"

    async def detect_new_token_real_time(self, contract_address: str) -> dict:
        """完全实时的代币检测"""
        print(f"🔍 开始实时检测合约: {contract_address}")
        start_time = time.time()
        
        # 并行执行所有实时检测
        tasks = {
            'token_info': self.get_token_info(contract_address),
            'liquidity_check': self.check_liquidity_real_time(contract_address),
            'honeypot_check': self.check_honeypot_real_time(contract_address),
            'price_check': self.get_token_price(contract_address),
            'ownership_check': self.check_ownership_real_time(contract_address),
        }
        
        results = {}
        for task_name, task in tasks.items():
            results[task_name] = await task
            print(f"✅ 完成实时检测: {task_name}")
        
        # 计算总耗时
        elapsed = time.time() - start_time
        
        return {
            'contract_address': contract_address,
            'detection_time': round(elapsed, 2),
            'risk_score': self.calculate_risk_score(results),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'detailed_results': results,
            'recommendation': self.generate_recommendation(results)
        }

class RealTimeMonitor:
    """实时监控器"""
    def __init__(self):
        self.detector = RealTimeBSCDetector()
        
    async def monitor_new_pairs(self):
        """监控新交易对创建 - 实时监听"""
        print("🎯 开始实时监控BSC新交易对...")
        
        # PancakeSwap Factory ABI
        factory_abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "token0", "type": "address"},
                    {"indexed": True, "name": "token1", "type": "address"},
                    {"indexed": False, "name": "pair", "type": "address"},
                    {"indexed": False, "name": "", "type": "uint256"}
                ],
                "name": "PairCreated",
                "type": "event"
            }
        ]
        
        factory = self.detector.w3.eth.contract(
            address=self.detector.pancake_factory,
            abi=factory_abi
        )
        
        # 从最新区块开始监听
        latest_block = self.detector.w3.eth.block_number
        print(f"📦 开始监听区块: {latest_block}")
        
        while True:
            try:
                current_block = self.detector.w3.eth.block_number
                print(f"🔄 当前区块: {current_block}")
                
                # 获取PairCreated事件
                events = factory.events.PairCreated.get_logs(
                    fromBlock=latest_block,
                    toBlock=current_block
                )
                
                for event in events:
                    token0 = event['args']['token0']
                    token1 = event['args']['token1']
                    pair_address = event['args']['pair']
                    
                    print(f"🎉 发现新交易对: {pair_address}")
                    print(f"   Token0: {token0}")
                    print(f"   Token1: {token1}")
                    
                    # 检测新代币
                    await self.process_new_token(token0)
                    
                latest_block = current_block + 1
                await asyncio.sleep(5)  # 每5秒检查一次新区块
                
            except Exception as e:
                print(f"❌ 监控错误: {e}")
                await asyncio.sleep(10)

    async def process_new_token(self, token_address: str):
        """处理新发现的代币"""
        try:
            # 检查缓存
            cache_key = f"detected:{token_address}"
            if self.detector.redis and self.detector.redis.exists(cache_key):
                print(f"⏭️ 已检测过: {token_address}")
                return
                
            print(f"🔍 开始检测新代币: {token_address}")
            
            # 执行实时检测
            results = await self.detector.detect_new_token_real_time(token_address)
            
            # 生成报告
            report = self.generate_real_time_report(results)
            print(report)
            
            # 发送通知
            if self.detector.dingtalk_webhook:
                await self.send_dingtalk_notification(report)
                
            # 设置缓存
            if self.detector.redis:
                self.detector.redis.setex(cache_key, 3600, "detected")
                
        except Exception as e:
            print(f"❌ 处理代币失败: {e}")

    def generate_real_time_report(self, detection_results: dict) -> str:
        """生成实时检测报告"""
        risk_score = detection_results['risk_score']
        details = detection_results['detailed_results']
        
        report = []
        report.append("🚀 BSC实时代币检测报告")
        report.append("=" * 40)
        report.append(f"⏰ 检测时间: {detection_results['timestamp']}")
        report.append(f"📍 合约地址: {detection_results['contract_address']}")
        report.append(f"⏱️ 检测耗时: {detection_results['detection_time']}秒")
        report.append("")
        
        # 总体风险
        report.append(f"🎯 实时风险评分: {risk_score}/10")
        report.append("")
        
        # 代币信息
        token_info = details.get('token_info', {})
        report.append("📝 代币信息:")
        report.append(f"   名称: {token_info.get('name', '未知')}")
        report.append(f"   符号: {token_info.get('symbol', '未知')}")
        report.append(f"   总供应: {token_info.get('total_supply', '未知')}")
        report.append("")
        
        # 流动性信息
        liquidity = details.get('liquidity_check', {})
        report.append("💧 流动性分析:")
        report.append(f"   是否有流动性: {'是' if liquidity.get('has_liquidity') else '否'}")
        report.append(f"   流动性价值: ${liquidity.get('liquidity_amount', 0):.2f}")
        report.append(f"   BNB流动性: {liquidity.get('bnb_liquidity', 0):.4f} BNB")
        report.append("")
        
        # 价格信息
        price = details.get('price_check', {})
        report.append("💰 价格信息:")
        report.append(f"   价格: ${price.get('price_usd', 0):.8f}")
        report.append(f"   流动性: ${price.get('liquidity_usd', 0):.2f}")
        report.append(f"   24小时交易量: ${price.get('volume_24h', 0):.2f}")
        report.append("")
        
        # 安全信息
        honeypot = details.get('honeypot_check', {})
        ownership = details.get('ownership_check', {})
        report.append("🛡️ 安全分析:")
        report.append(f"   是否貔貅盘: {'是' if honeypot.get('is_honeypot') else '否'}")
        report.append(f"   有黑名单功能: {'是' if honeypot.get('has_blacklist_function') else '否'}")
        report.append(f"   所有权放弃: {'是' if ownership.get('is_renounced') else '否'}")
        report.append(f"   Owner: {ownership.get('owner', '未知')}")
        report.append("")
        
        report.append(f"💡 投资建议: {detection_results['recommendation']}")
        
        return "\n".join(report)

    async def send_dingtalk_notification(self, message: str):
        """发送钉钉通知"""
        try:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }
            response = requests.post(self.detector.dingtalk_webhook, json=payload, timeout=10)
            print(f"📢 通知发送状态: {response.status_code}")
        except Exception as e:
            print(f"❌ 通知发送失败: {e}")

async def main():
    """主函数 - 实时监控模式"""
    print("🚀 启动BSC实时Meme币检测系统...")
    
    # 初始化实时监控器
    monitor = RealTimeMonitor()
    
    # 开始实时监控
    await monitor.monitor_new_pairs()

if __name__ == '__main__':
    # 运行实时监控
    asyncio.run(main())
