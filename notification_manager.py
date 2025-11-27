import aiohttp
import logging
import time
import hmac
import hashlib
import base64
from urllib.parse import quote
from datetime import datetime

class NotificationManager:
    def __init__(self, config, event_listener=None):  # 🎯 新增：接收event_listener引用
        self.config = config
        self.event_listener = event_listener  # 🎯 新增：事件监听器引用
        self.logger = logging.getLogger(__name__)
        self.last_limit_notification_time = 0  # 🎯 新增：限制通知时间记录

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

    async def send_dingtalk_notification(self, risk_report, detection_time):
        """🎯 修改：添加限制检查的钉钉通知"""
        # 🎯 新增：限制状态检查
        if self._is_daily_limit_reached():
            # 在限制状态下，只发送重要的通知或减少通知频率
            if risk_report.get('status') == 'skipped':
                self.logger.debug("⏭️ 限制状态下跳过常规通知")
                return False
                
            # 每30分钟发送一次限制状态提醒
            current_time = time.time()
            if current_time - self.last_limit_notification_time > 1800:  # 30分钟
                success = await self._send_limit_reached_notification()
                if success:
                    self.last_limit_notification_time = current_time
                return success
            return False
        
        # 正常的通知逻辑
        try:
            # 构建风险报告消息
            message = self._build_risk_notification(risk_report, detection_time)
            return await self.send_dingtalk_message(message)
        except Exception as e:
            self.logger.error(f"发送钉钉通知失败: {e}")
            return False

    async def _send_limit_reached_notification(self):
        """🎯 新增：发送达到限制的通知"""
        if not self.event_listener:
            return False
            
        scan_info = f"{self.event_listener.scan_count_today}/{self.event_listener.daily_scan_limit}"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "🔔 扫描限制提醒",
                "text": f"**BSC Meme检测系统**\n\n"
                       f"⏸️ **系统状态**: 今日扫描已达上限\n"
                       f"📊 **扫描进度**: {scan_info}\n"
                       f"⏰ **下次重置**: 明日 00:00\n"
                       f"💡 **说明**: 系统已进入待机模式，避免API限制\n\n"
                       f"系统将在明日自动恢复扫描任务。"
            }
        }
        
        try:
            success = await self.send_dingtalk_message(message)
            if success:
                self.logger.info("✅ 限制状态通知发送成功")
            return success
        except Exception as e:
            self.logger.error(f"限制状态通知发送失败: {e}")
            return False

    def _build_risk_notification(self, risk_report, detection_time):
        """构建风险通知消息"""
        token_address = risk_report.get('token_address', 'Unknown')
        token_name = risk_report.get('token_name', 'Unknown')
        token_symbol = risk_report.get('token_symbol', 'Unknown')
        
        # 🎯 新增：添加系统状态信息
        system_status = ""
        if self.event_listener:
            status = self.event_listener.get_system_status()
            system_status = f"\n**系统状态**: {status['status']} ({status['scan_count_today']}/{status['daily_scan_limit']})"
        
        # 构建消息内容
        text = f"## 🔍 检测到新代币\n\n"
        text += f"**代币名称**: {token_name} ({token_symbol})\n"
        text += f"**代币地址**: `{token_address}`\n"
        text += f"**检测耗时**: {detection_time:.2f}秒{system_status}\n\n"
        
        # 添加风险信息
        risks = risk_report.get('risks', {})
        if risks:
            text += "### 风险分析\n"
            for risk_type, risk_info in risks.items():
                if risk_type == 'honeypot' and risk_info.get('is_honeypot', False):
                    text += "❌ **貔貅盘风险**: 检测到貔貅盘特征\n"
                if risk_type == 'tax_rate' and risk_info.get('high_tax', False):
                    text += f"⚠️ **高交易税**: 买入{risk_info.get('buy_tax', 0)}%/卖出{risk_info.get('sell_tax', 0)}%\n"
        
        # 添加进度条信息
        progress_bars = risk_report.get('progress_bars', {})
        if progress_bars:
            text += "\n### 详细评估\n"
            for bar_name, bar_value in progress_bars.items():
                text += f"- {bar_name}: {bar_value}\n"
        
        # 添加徽章信息
        badges = risk_report.get('badges', {})
        if badges:
            text += "\n### 特征标签\n"
            for badge_name, badge_value in badges.items():
                text += f"- {badge_name}: {badge_value}\n"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"新代币检测: {token_symbol}",
                "text": text
            }
        }
        return message

    async def send_test_notification(self):
        """🎯 修改：添加系统状态信息的测试通知"""
        try:
            # 获取系统状态
            system_status = "正常运行中"
            scan_info = ""
            
            if self.event_listener:
                status = self.event_listener.get_system_status()
                system_status = status["status"]
                scan_info = f"**扫描进度**: {status['scan_count_today']}/{status['daily_scan_limit']}\n"
            
            test_message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "🔔 测试通知",
                    "text": f"## 测试通知 ✅\n\n" +
                           f"**服务**: BSC Meme币检测器\n" +
                           f"**系统状态**: {system_status}\n" +
                           f"{scan_info}" +
                           f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" +
                           f"这是一条测试消息，用于验证钉钉通知功能是否正常工作。"
                }
            }
            
            success = await self.send_dingtalk_message(test_message)
            self.logger.info(f"测试通知发送{'成功' if success else '失败'}")
            return success
            
        except Exception as e:
            self.logger.error(f"发送测试通知时出错: {e}")
            return False

    def _is_daily_limit_reached(self):
        """🎯 新增：检查是否达到每日限制"""
        if self.event_listener and hasattr(self.event_listener, 'is_limit_reached'):
            return self.event_listener.is_limit_reached
        return False
