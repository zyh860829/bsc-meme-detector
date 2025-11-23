import aiohttp
import logging
from datetime import datetime

class NotificationManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

    async def send_dingtalk_message(self, message):
        """发送钉钉消息"""
        if not self.config.DINGTALK_WEBHOOK:
            self.logger.error("钉钉webhook未配置")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.DINGTALK_WEBHOOK,
                    json=message,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
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
