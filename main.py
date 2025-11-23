import asyncio
import logging
import signal
import sys
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
        """初始化系统"""
        self.logger.info("初始化Meme币检测系统...")
        
        # 调试：打印所有环境变量状态
        self.logger.info("=== 环境变量调试信息 ===")
        self.logger.info(f"BSC_NODES[0]: '{self.config.BSC_NODES[0]}'")
        self.logger.info(f"BSC_NODES[1]: '{self.config.BSC_NODES[1]}'")
        self.logger.info(f"DINGTALK_WEBHOOK: '{self.config.DINGTALK_WEBHOOK}'")
        self.logger.info(f"LOG_LEVEL: '{self.config.LOG_LEVEL}'")
        self.logger.info("========================")
        
        # 检查必要环境变量
        if not all([self.config.BSC_NODES[0], self.config.DINGTALK_WEBHOOK]):
            self.logger.error("缺少必要的环境变量配置")
            self.logger.error(f"BSC_NODES[0] 为空: {self.config.BSC_NODES[0] is None}")
            self.logger.error(f"DINGTALK_WEBHOOK 为空: {self.config.DINGTALK_WEBHOOK is None}")
            return False
        
        # 初始化管理器
        self.node_manager = NodeManager(self.config)
        self.cache_manager = CacheManager(self.config)
        self.event_listener = EventListener(self.config, self.node_manager, self.cache_manager)
        
        self.logger.info("系统初始化完成")
        return True

    async def start_http_server(self):
        """启动HTTP服务器绑定端口"""
        app = web.Application()
        
        # 添加健康检查接口
        app.router.add_get('/', self.health_check)
        app.router.add_get('/health', self.health_check)
        
        #添加测试钉钉通知接口
        app.router.add_get('/test-dingtalk', self.test_dingtalk)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        # 绑定到所有接口的8080端口
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        
        self.logger.info("HTTP服务器已启动在端口8080")
    
    async def health_check(self, request):
        """健康检查接口"""
        return web.json_response({
            "status": "running", 
            "service": "bsc-meme-detector",
            "timestamp": asyncio.get_event_loop().time()
        })
    
    # 🆕🆕🆕 新增的测试方法 🆕🆕🆕
async def test_dingtalk(self, request):
    """测试钉钉通知"""
    from notification_manager import NotificationManager
    
    self.logger.info("接收到钉钉测试请求")
    
    try:
        notifier = NotificationManager(self.config)
        success = await notifier.send_test_notification()
        
        if success:
            self.logger.info("测试通知发送成功")
            return web.Response(text="✅ 测试通知发送成功！请检查钉钉群")
        else:
            self.logger.error("测试通知发送失败")
            return web.Response(text="❌ 测试通知发送失败，请检查配置")
            
    except Exception as e:
        self.logger.error(f"测试过程中发生错误: {e}")
        return web.Response(text=f"❌ 测试错误: {str(e)}")
        # 🆕🆕🆕 新增结束 🆕🆕🆕
    
    async def start(self):
        """启动系统"""
        if not await self.initialize():
            self.logger.error("系统初始化失败")
            return
        
        self.is_running = True
        self.logger.info("启动Meme币检测系统...")
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # 启动HTTP服务器（绑定端口）
            await self.start_http_server()
            
            # 启动事件监听（在后台运行）
            asyncio.create_task(self.event_listener.start_listening())
            
            # 保持程序运行
            while self.is_running:
                await asyncio.sleep(1)
                
        except Exception as e:
            self.logger.error(f"系统运行异常: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """关闭系统"""
        self.is_running = False
        self.logger.info("正在关闭系统...")
        
        if self.event_listener:
            self.event_listener.is_running = False
        
        self.logger.info("系统已关闭")
    
    def signal_handler(self, signum, frame):
        """信号处理"""
        self.logger.info(f"接收到信号 {signum}, 正在关闭...")
        asyncio.create_task(self.shutdown())

async def main():
    """主函数"""
    detector = MemeTokenDetector()
    await detector.start()

if __name__ == "__main__":
    asyncio.run(main())
