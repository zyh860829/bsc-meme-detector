import aiohttp
import logging
import time
import hmac
import hashlib
import base64
from urllib.parse import quote
from datetime import datetime

class NotificationManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

    def _generate_dingtalk_sign(self, timestamp, secret):
        """生成钉钉签名"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'), 
            string_to_sign.encode('utf-8'), 
            hashlib.sha256
        ).digest()
        sign = quote(base64.b64encode(hmac_code))
        return sign

    async def send_dingtalk_message(self, message):
        """发送钉钉消息"""
        if not self.config.DINGTALK_WEBHOOK:
            self.logger.error("钉钉webhook未配置")
            return False

        # 如果有加签，生成签名
        webhook_url = self.config.DINGTALK_WEBHOOK
        if hasattr(self.config, 'DINGTALK_SECRET') and self.config.DINGTALK_SECRET:
            timestamp = str(round(time.time() * 1000))
            secret = self.config.DINGTALK_SECRET
            sign = self._generate_dingtalk_sign(timestamp, secret)
            webhook_url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"
            self.logger.info(f"使用加签的webhook URL")

        self.logger.info(f"准备发送钉钉消息到: {webhook_url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=message,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response_text = await response.text()
                    self.logger.info(f"钉钉响应状态: {response.status}")
                    self.logger.info(f"钉钉响应内容: {response_text}")
                    
                    if response.status == 200:
                        result = await response.json()
                        if result.get('errcode') == 0:
                            self.logger.info("钉钉消息发送成功")
                            return True
                        else:
                            self.logger.error(f"钉钉返回错误: {result}")
                            return False
                    else:
                        self.logger.error(f"钉钉请求失败，状态码: {response.status}")
                        return False
        except Exception as e:
            self.logger.error(f"发送钉钉消息时发生异常: {e}")
            return False

    async def send_test_notification(self):
        """发送测试通知"""
        try:
            test_message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "🔔 测试通知",
                    "text": f"## 测试通知 ✅\n\n" +
                           f"**服务**: BSC Meme币检测器\n" +
                           f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" +
                           f"**状态**: 运行正常\n\n" +
                           f"这是一条测试消息，用于验证钉钉通知功能是否正常工作。"
                }
            }
            
            success = await self.send_dingtalk_message(test_message)
            self.logger.info(f"测试通知发送{'成功' if success else '失败'}")
            return success
            
        except Exception as e:
            self.logger.error(f"发送测试通知时出错: {e}")
            return False
