import aiohttp
import json
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
from tenacity import retry, stop_after_attempt, wait_exponential

class NotificationManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def _sign_dingtalk_url(self, webhook_url, secret):
        """对钉钉Webhook URL进行签名"""
        if not secret:
            return webhook_url
            
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'), 
            string_to_sign.encode('utf-8'), 
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        # 添加签名参数到URL
        signed_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"
        return signed_url
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
    async def send_dingtalk_notification(self, risk_report, detection_time):
        """发送钉钉通知（支持Secret签名）"""
        if not self.config.DINGTALK_WEBHOOK:
            self.logger.warning("钉钉Webhook未配置，跳过通知")
            return
        
        try:
            # 对URL进行签名（如果有Secret）
            webhook_url = self._sign_dingtalk_url(
                self.config.DINGTALK_WEBHOOK, 
                self.config.DINGTALK_SECRET
            )
            
            message = self._build_dingtalk_message(risk_report, detection_time)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=message,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == 200:
                        self.logger.info("钉钉通知发送成功")
                    else:
                        response_text = await response.text()
                        self.logger.error(f"钉钉通知发送失败: {response.status}, {response_text}")
                        raise Exception(f"HTTP {response.status}")
                        
        except Exception as e:
            self.logger.error(f"发送钉钉通知失败: {e}")
            raise
    
    def _build_dingtalk_message(self, risk_report, detection_time):
        """构建钉钉消息"""
        token_address_short = f"{risk_report['token_address'][:6]}...{risk_report['token_address'][-4:]}"
        
        # 构建消息内容
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "🚨 Meme币风险检测报告",
                "text": f"## 🚨 Meme币风险检测报告\n\n"
                       f"**代币信息**\n"
                       f"- 名称: {risk_report.get('token_name', 'Unknown')} ({risk_report.get('token_symbol', 'Unknown')})\n"
                       f"- 合约: `{risk_report['token_address']}` \n"
                       f"- 检测耗时: {detection_time:.2f}秒\n\n"
                       f"**风险维度分析**\n"
            }
        }
        
        # 添加进度条
        progress_bars = risk_report.get('progress_bars', {})
        for key, bar in progress_bars.items():
            if key == 'transaction_restrictions':
                message['markdown']['text'] += f"1. 交易限制检测 🛡️\n   {bar}\n\n"
            elif key == 'permission_backdoor':
                message['markdown']['text'] += f"2. 权限后门检测 🔑\n   {bar}\n\n"
            elif key == 'economic_model':
                message['markdown']['text'] += f"3. 经济模型风险 💰\n   {bar}\n\n"
            elif key == 'security_vulnerabilities':
                message['markdown']['text'] += f"4. 安全漏洞检测 🚨\n   {bar}\n\n"
        
        # 添加徽章
        message['markdown']['text'] += "**详细检测项**\n"
        badges = risk_report.get('badges', {})
        for key, badge in badges.items():
            if key == 'premine_detection':
                message['markdown']['text'] += f"- 预挖矿检测 ⛏️: {badge}\n"
            elif key == 'presale_situation':
                message['markdown']['text'] += f"- 预售情况 🏷️: {badge}\n"
            elif key == 'whitelist_mechanism':
                message['markdown']['text'] += f"- 白名单机制 📋: {badge}\n"
            elif key == 'lp_burn':
                message['markdown']['text'] += f"- LP代币销毁 🔥: {badge}\n"
            elif key == 'community_driven':
                message['markdown']['text'] += f"- 社区驱动 👥: {badge}\n"
        
        # 添加风险提示
        message['markdown']['text'] += f"\n**⚠️ 风险提示**\n"
        message['markdown']['text'] += "本报告仅用于技术研究目的，不构成任何投资建议。\n"
        message['markdown']['text'] += "加密货币投资风险极高，请谨慎决策。\n\n"
        message['markdown']['text'] += f"*检测时间: {risk_report.get('detection_time', '')}*"
        
        return message

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=3))
    async def send_test_notification(self):
        """发送测试通知"""
        if not self.config.DINGTALK_WEBHOOK:
            self.logger.warning("钉钉Webhook未配置，跳过测试通知")
            return False
        
        try:
            # 创建测试报告
            test_report = {
                'token_address': '0x1234567890abcdef1234567890abcdef12345678',
                'token_name': 'Test Token',
                'token_symbol': 'TEST',
                'detection_time': '2024-01-01 12:00:00',
                'progress_bars': {
                    'transaction_restrictions': '[==========] 无限制',
                    'permission_backdoor': '[=====-----] 部分风险',
                    'economic_model': '[==========] 模型合理',
                    'security_vulnerabilities': '[----------] 高风险'
                },
                'badges': {
                    'premine_detection': '✅ 无预挖矿',
                    'presale_situation': '⚠️ 少量预售',
                    'whitelist_mechanism': '❌ 无白名单',
                    'lp_burn': '✅ 已销毁',
                    'community_driven': '✅ 社区驱动'
                }
            }
            
            await self.send_dingtalk_notification(test_report, 5.5)
            self.logger.info("测试通知发送成功")
            return True
            
        except Exception as e:
            self.logger.error(f"发送测试通知失败: {e}")
            return False
