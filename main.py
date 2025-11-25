import asyncio
import logging
import signal
import sys
import os
from aiohttp import web
from config import Config
from node_manager import NodeManager
from cache_manager import CacheManager
from event_listener import EventListener

class MemeTokenDetector:
    def __init__(self):
        self.config = Config()
        self.setup_logging()
        self.node_manager = None
        self.cache_manager = None
        self.event_listener = None
        self.is_running = False
        self.http_runner = None  # 新增：存储HTTP runner

    def setup_logging(self):
        """配置日志"""
        logging.basicConfig(
            level=getattr(logging, self.config.LOG_LEVEL),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('meme_detector.log')
            ]
        )
        self.logger = logging.getLogger(__name__)

    async def initialize(self):
        """初始化系统 - 增加环境变量检查"""
        self.logger.info("初始化Meme币检测系统...")

        # ✅ 新增：检查必要环境变量
        required_vars = ['DINGTALK_WEBHOOK', 'REDIS_URL']
        missing_vars = [var for var in required_vars if not getattr(self.config, var, None)]
        if missing_vars:
            self.logger.error(f"❌ 缺少必要环境变量: {missing_vars}")
            return False

        # 原有初始化逻辑
        self.node_manager = NodeManager(self.config)
        self.cache_manager = CacheManager(self.config)
        self.event_listener = EventListener(self.config, self.node_manager, self.cache_manager)
        
        await self.node_manager.start()

        self.logger.info("✅ 系统初始化完成")
        return True

    async def start_http_server(self):
        """启动HTTP服务器 - 返回runner用于清理"""
        app = web.Application()
        app.router.add_get('/', self.health_check)
        app.router.add_get('/health', self.health_check)
        app.router.add_get('/test-dingtalk', self.test_dingtalk)

        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(self.config.PORT) if hasattr(self.config, 'PORT') and self.config.PORT else 8080
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        
        self.http_runner = runner  # 存储runner
        self.logger.info(f"✅ HTTP服务器已启动在端口 {port}")

    async def health_check(self, request):
        return web.json_response({
            "status": "running", 
            "service": "bsc-meme-detector",
            "timestamp": asyncio.get_event_loop().time()
        })

    async def test_dingtalk(self, request):
        from notification_manager import NotificationManager
        try:
            notifier = NotificationManager(self.config)
            success = await notifier.send_test_notification()
            if success:
                return web.Response(text="✅ 测试通知发送成功！请检查钉钉群")
            else:
                return web.Response(text="❌ 测试通知发送失败，请检查配置")
        except Exception as e:
            return web.Response(text=f"❌ 测试错误: {str(e)}")

    async def start(self):
        """启动系统 - 增加信号处理"""
        if not await self.initialize():
            self.logger.error("系统初始化失败")
            return

        self.is_running = True
        
        # ✅ 新增：注册信号处理
        loop = asyncio.get_event_loop()
        for signame in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda: asyncio.create_task(self.shutdown())
            )

        try:
            await self.start_http_server()
            asyncio.create_task(self.event_listener.start_listening())
            
            # 保持程序运行
            while self.is_running:
                await asyncio.sleep(1)
                
        except Exception as e:
            self.logger.error(f"系统运行异常: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """关闭系统 - 完善资源清理"""
        if not self.is_running:
            return
            
        self.is_running = False
        self.logger.info("正在关闭系统...")

        # 关闭事件监听器
        if self.event_listener:
            self.event_listener.is_running = False

        # ✅ 新增：关闭NodeManager
        if self.node_manager:
            await self.node_manager.close()

        # ✅ 新增：关闭HTTP服务器
        if self.http_runner:
            await self.http_runner.cleanup()

        self.logger.info("✅ 系统已关闭")

def handle_sigterm(signum, frame):
    """处理SIGTERM信号"""
    print(f"\n⚠️ 收到信号 {signum}，准备优雅退出...")
    sys.exit(0)

async def main():
    detector = MemeTokenDetector()
    await detector.start()

if __name__ == "__main__":
    # ✅ 注册SIGTERM处理器
    signal.signal(signal.SIGTERM, handle_sigterm)
    asyncio.run(main())
