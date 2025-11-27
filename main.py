import asyncio
import logging
import signal
import sys
import os
import fcntl  # ✅ 新增：文件锁
import redis  # ✅ 新增：Redis客户端
import time   # ✅ 新增：时间模块
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
        self.http_runner = None
        self.lock_file = None  # ✅ 新增：锁文件
        
        # ✅ 新增：Redis分布式锁相关
        self.redis_client = None
        self.lock_key = "meme_detector_instance_lock"
        self.instance_id = f"instance_{int(time.time())}_{os.getpid()}"
        self.lock_renewal_task = None

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

    def acquire_instance_lock(self):
        """✅ 新增：获取实例锁，确保单实例运行"""
        try:
            self.lock_file = open('/tmp/meme_detector.lock', 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.logger.info("✅ 获取实例锁成功，单实例运行")
            return True
        except (IOError, BlockingIOError):
            self.logger.error("❌ 另一个实例正在运行，退出当前实例")
            return False

    def release_instance_lock(self):
        """✅ 新增：释放实例锁"""
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                self.logger.info("✅ 释放实例锁")
            except:
                pass

    def acquire_distributed_lock(self):
        """✅ 修改：安全版分布式锁获取 - 自动处理死锁"""
        try:
            self.redis_client = redis.from_url(self.config.REDIS_URL)
            
            # 先检查锁状态
            current_lock = self.redis_client.get(self.lock_key)
            if current_lock:
                ttl = self.redis_client.ttl(self.lock_key)
                self.logger.info(f"发现现有锁: {current_lock.decode()}, TTL: {ttl}秒")
                
                # 如果TTL很短或为-1（无过期时间），清理它
                if ttl == -1 or ttl < 10:
                    self.logger.warning("清理过期或无过期时间的锁")
                    self.redis_client.delete(self.lock_key)
            
            # 获取新锁（设置较短过期时间）
            acquired = self.redis_client.set(
                self.lock_key, 
                self.instance_id, 
                ex=30,  # 缩短为30秒
                nx=True
            )
            
            if acquired:
                self.logger.info("✅ 获取分布式锁成功")
                self.lock_renewal_task = asyncio.create_task(self._renew_lock())
                return True
            else:
                # 最后检查一次
                ttl = self.redis_client.ttl(self.lock_key)
                if ttl > 0:
                    self.logger.warning(f"锁被占用，等待{ttl}秒")
                    time.sleep(ttl + 1)
                    return self.acquire_distributed_lock()
                return False
                
        except Exception as e:
            self.logger.error(f"获取分布式锁失败: {e}")
            # 在异常情况下，允许继续运行（降级处理）
            return True

    async def _renew_lock(self):
        """✅ 修改：定期续期锁 - 适配新的30秒过期时间"""
        while self.is_running:
            try:
                self.redis_client.expire(self.lock_key, 30)  # 改为30秒
                await asyncio.sleep(20)  # 每20秒续期一次（在过期前10秒续期）
            except Exception as e:
                self.logger.error(f"锁续期失败: {e}")
                break

    def release_distributed_lock(self):
        """✅ 新增：释放分布式锁"""
        try:
            if self.redis_client:
                # 只释放自己持有的锁
                current_holder = self.redis_client.get(self.lock_key)
                if current_holder and current_holder.decode() == self.instance_id:
                    self.redis_client.delete(self.lock_key)
                    self.logger.info("✅ 释放分布式锁成功")
        except Exception as e:
            self.logger.error(f"释放分布式锁失败: {e}")

    async def initialize(self):
        """初始化系统 - 增加环境变量检查"""
        self.logger.info("初始化Meme币检测系统...")

        # ✅ 新增：检查单实例锁
        if not self.acquire_instance_lock():
            return False

        # ✅ 修改：检查分布式锁 - 现在在失败时会降级处理
        if not self.acquire_distributed_lock():
            self.logger.warning("⚠️ 分布式锁获取失败，但系统将继续运行（降级模式）")
            # 注意：这里不再返回False，而是继续运行

        # ✅ 新增：检查必要环境变量
        required_vars = ['DINGTALK_WEBHOOK', 'REDIS_URL']
        missing_vars = [var for var in required_vars if not getattr(self.config, var, None)]
        if missing_vars:
            self.logger.error(f"❌ 缺少必要环境变量: {missing_vars}")
            self.release_instance_lock()
            self.release_distributed_lock()
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

        # 取消锁续期任务
        if self.lock_renewal_task:
            self.lock_renewal_task.cancel()

        # 关闭事件监听器
        if self.event_listener:
            self.event_listener.is_running = False

        # ✅ 新增：关闭NodeManager
        if self.node_manager:
            await self.node_manager.close()

        # ✅ 新增：关闭HTTP服务器
        if self.http_runner:
            await self.http_runner.cleanup()

        # ✅ 新增：释放实例锁
        self.release_instance_lock()
        
        # ✅ 新增：释放分布式锁
        self.release_distributed_lock()

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
