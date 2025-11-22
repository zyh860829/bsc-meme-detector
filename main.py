import asyncio
import logging
import signal
import sys
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
        
        # 检查必要环境变量
        if not all([self.config.BSC_NODES[0], self.config.DINGTALK_WEBHOOK]):
            self.logger.error("缺少必要的环境变量配置")
            return False
        
        # 初始化管理器
        self.node_manager = NodeManager(self.config)
        self.cache_manager = CacheManager(self.config)
        self.event_listener = EventListener(self.config, self.node_manager, self.cache_manager)
        
        self.logger.info("系统初始化完成")
        return True
    
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
            # 启动事件监听
            await self.event_listener.start_listening()
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
