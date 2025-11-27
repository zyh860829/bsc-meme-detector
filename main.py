import asyncio
import logging
import signal
import sys
import os
import fcntl
import redis
import time
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
        self.lock_file = None
        
        # Redis锁相关
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
        """获取实例锁"""
        try:
            self.lock_file = open('/tmp/meme_detector.lock', 'w')
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.logger.info("✅ 获取实例锁成功")
            return True
        except (IOError, BlockingIOError):
            self.logger.error("❌ 另一个实例正在运行")
            return False

    def acquire_distributed_lock(self):
        """紧急修复版：强制清理异常锁"""
        try:
            self.redis_client = redis.from_url(self.config.REDIS_URL)
            
            # 强制删除所有可能的异常锁
            self.redis_client.delete(self.lock_key)
            self.logger.info("✅ 强制清理Redis锁完成")
            
            # 获取新锁（设置更短过期时间）
            acquired = self.redis_client.set(
                self.lock_key, 
                self.instance_id, 
                ex=10,  # 缩短为10秒
                nx=True
            )
            
            if acquired:
                self.logger.info("✅ 获取分布式锁成功")
                return True
            else:
                self.logger.error("❌ 获取分布式锁失败，但继续运行")
                return True  # 降级处理
                
        except Exception as e:
            self.logger.error(f"获取分布式锁失败: {e}")
            return True  # 异常时也继续运行

    async def initialize(self):
        """🎯 修改：调整初始化顺序以正确传递event_listener引用"""
        self.logger.info("初始化Meme币检测系统...")

        # 检查单实例锁
        if not self.acquire_instance_lock():
            return False

        # 检查分布式锁（现在失败也会继续）
        if not self.acquire_distributed_lock():
            self.logger.warning("⚠️ 分布式锁获取失败，但系统将继续运行")

        # 检查必要环境变量
        required_vars = ['DINGTALK_WEBHOOK', 'REDIS_URL']
        missing_vars = [var for var in required_vars if not getattr(self.config, var, None)]
        if missing_vars:
            self.logger.error(f"❌ 缺少必要环境变量: {missing_vars}")
            return False

        # 🎯 修改：调整初始化顺序
        # 先创建基础组件
        self.node_manager = NodeManager(self.config)
        self.cache_manager = CacheManager(self.config)
        
        # 然后创建事件监听器
        self.event_listener = EventListener(self.config, self.node_manager, self.cache_manager)
        
        # 🎯 新增：将event_listener引用传递给其他组件
        self.node_manager.event_listener = self.event_listener
        
        await self.node_manager.start()
        self.logger.info("✅ 系统初始化完成")
        return True

    async def start_http_server(self):
        """启动HTTP服务器 - 修复端口绑定"""
        app = web.Application()
        app.router.add_get('/', self.health_check)
        app.router.add_get('/health', self.health_check)
        app.router.add_get('/status', self.system_status)  # 🎯 新增：系统状态端点
        app.router.add_get('/test-dingtalk', self.test_dingtalk)

        runner = web.AppRunner(app)
        await runner.setup()
        
        # 确保使用Render提供的PORT环境变量
        port = int(os.getenv('PORT', '8080'))
        self.logger.info(f"🚀 启动HTTP服务器在端口: {port}")
        
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        
        self.http_runner = runner
        self.logger.info(f"✅ HTTP服务器已成功启动在端口 {port}")

    async def health_check(self, request):
        """🎯 改进的健康检查端点"""
        # 基础健康检查
        base_health = {
            "status": "running", 
            "service": "bsc-meme-detector",
            "timestamp": time.time(),
            "version": "1.0.0"
        }
        
        # 添加组件状态
        try:
            if self.event_listener:
                scanner_status = self.event_listener.get_system_status()
                base_health["scanner"] = scanner_status
                
                # 根据扫描器状态确定整体健康状态
                if scanner_status["status"] == "limited":
                    base_health["overall_status"] = "limited"
                    base_health["message"] = "扫描任务已完成，系统待机中"
                else:
                    base_health["overall_status"] = "active"
                    base_health["message"] = "系统正常运行中"
            else:
                base_health["scanner"] = {"status": "not_initialized"}
                base_health["overall_status"] = "initializing"
                
        except Exception as e:
            base_health["scanner"] = {"status": "error", "error": str(e)}
            base_health["overall_status"] = "degraded"
            
        return web.json_response(base_health)

    async def system_status(self, request):
        """🎯 新增：详细系统状态端点"""
        try:
            status_data = {
                "timestamp": time.time(),
                "service": "bsc-meme-detector",
                "components": {}
            }
            
            # 事件监听器状态
            if self.event_listener:
                status_data["components"]["event_listener"] = self.event_listener.get_system_status()
            else:
                status_data["components"]["event_listener"] = {"status": "not_initialized"}
                
            # 节点管理器状态
            if self.node_manager:
                # 🎯 改进：添加更详细的节点信息
                status_data["components"]["node_manager"] = {
                    "status": "running",
                    "http_nodes_count": len(self.node_manager.http_nodes) if hasattr(self.node_manager, 'http_nodes') else 0,
                    "websocket_nodes_count": len(self.node_manager.ws_nodes) if hasattr(self.node_manager, 'ws_nodes') else 0,
                    "healthy_http_nodes": len([n for n in self.node_manager.http_nodes if n.get('healthy', False)]) if hasattr(self.node_manager, 'http_nodes') else 0,
                    "has_event_listener": self.node_manager.event_listener is not None
                }
            else:
                status_data["components"]["node_manager"] = {"status": "not_initialized"}
                
            # 缓存管理器状态
            if self.cache_manager:
                status_data["components"]["cache_manager"] = {
                    "status": "running",
                    "backend": "redis"  # 假设使用Redis
                }
            else:
                status_data["components"]["cache_manager"] = {"status": "not_initialized"}
                
            # 计算整体状态
            component_statuses = [comp.get("status") for comp in status_data["components"].values()]
            if all(status == "running" for status in component_statuses):
                status_data["overall_status"] = "healthy"
            elif "limited" in component_statuses:
                status_data["overall_status"] = "limited"
            elif "not_initialized" in component_statuses:
                status_data["overall_status"] = "initializing"
            else:
                status_data["overall_status"] = "degraded"
                
            return web.json_response(status_data)
            
        except Exception as e:
            return web.json_response({
                "error": f"获取系统状态失败: {str(e)}",
                "timestamp": time.time()
            }, status=500)

    async def test_dingtalk(self, request):
        """🎯 修改：使用带有event_listener引用的NotificationManager"""
        try:
            from notification_manager import NotificationManager
            # 🎯 修改：传递event_listener引用
            notifier = NotificationManager(self.config, self.event_listener)
            success = await notifier.send_test_notification()
            if success:
                return web.Response(text="✅ 测试通知发送成功！请检查钉钉群")
            else:
                return web.Response(text="❌ 测试通知发送失败，请检查配置")
        except Exception as e:
            return web.Response(text=f"❌ 测试错误: {str(e)}")

    async def start(self):
        """启动系统"""
        if not await self.initialize():
            self.logger.error("系统初始化失败")
            return

        self.is_running = True
        
        # 注册信号处理
        loop = asyncio.get_event_loop()
        for signame in ('SIGINT', 'SIGTERM'):
            loop.add_signal_handler(
                getattr(signal, signame),
                lambda: asyncio.create_task(self.shutdown())
            )

        try:
            await self.start_http_server()
            asyncio.create_task(self.event_listener.start_listening())
            
            # 🎯 新增：启动状态监控任务
            asyncio.create_task(self._status_monitor())
            
            self.logger.info("✅ 所有服务已启动完成")
            self.logger.info("📊 可通过以下端点查看状态:")
            self.logger.info("   - /health    基础健康检查")
            self.logger.info("   - /status    详细系统状态")
            self.logger.info("   - /test-dingtalk 测试钉钉通知")
            
            # 🎯 新增：记录初始状态
            if self.event_listener:
                status = self.event_listener.get_system_status()
                self.logger.info(f"📈 初始状态: 扫描 {status['scan_count_today']}/{status['daily_scan_limit']} | 状态: {status['status']}")
            
            # 保持程序运行
            while self.is_running:
                await asyncio.sleep(1)
                
        except Exception as e:
            self.logger.error(f"系统运行异常: {e}")
        finally:
            await self.shutdown()

    async def _status_monitor(self):
        """🎯 新增：系统状态监控任务"""
        last_status_log_time = 0
        status_log_interval = 300  # 每5分钟记录一次状态
        
        while self.is_running:
            try:
                current_time = time.time()
                
                # 定期记录系统状态
                if current_time - last_status_log_time > status_log_interval:
                    if self.event_listener:
                        status = self.event_listener.get_system_status()
                        self.logger.info(
                            f"📊 系统状态监控 - "
                            f"扫描: {status['scan_count_today']}/{status['daily_scan_limit']} | "
                            f"状态: {status['status']} | "
                            f"区块: {status['processed_blocks_count']} | "
                            f"API错误: {status['api_limit_errors']}"
                        )
                    last_status_log_time = current_time
                    
            except Exception as e:
                self.logger.error(f"状态监控任务错误: {e}")
                
            await asyncio.sleep(60)  # 每分钟检查一次

    async def shutdown(self):
        """关闭系统"""
        if not self.is_running:
            return
            
        self.is_running = False
        self.logger.info("正在关闭系统...")

        # 关闭组件
        if self.event_listener:
            self.event_listener.is_running = False

        if self.node_manager:
            await self.node_manager.close()

        if self.http_runner:
            await self.http_runner.cleanup()

        # 释放锁
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
            except:
                pass

        self.logger.info("✅ 系统已关闭")

async def main():
    detector = MemeTokenDetector()
    await detector.start()

if __name__ == "__main__":
    asyncio.run(main())
