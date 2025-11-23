import asyncio
import json
import logging
import os
import websockets

class EventListener:
    def __init__(self, config, node_manager, cache_manager):
        self.config = config
        self.node_manager = node_manager
        self.cache_manager = cache_manager
        self.logger = logging.getLogger(__name__)
        self.is_running = False

    async def test_infura_connection(self):
        """测试Infura WebSocket连接"""
        self.logger.info("🚀 开始测试Infura WebSocket连接...")
        
        # 从环境变量获取Infura URL
        infura_url = os.getenv('INFURA_BSC_WS_URL')
        
        if not infura_url:
            self.logger.error("❌ 未找到INFURA_BSC_WS_URL环境变量")
            return False
            
        self.logger.info(f"使用Infura URL: {infura_url[:50]}...")  # 只显示前50个字符
        
        try:
            # 尝试连接Infura WebSocket
            self.logger.info("正在连接Infura WebSocket...")
            
            async with websockets.connect(
                infura_url,
                ping_interval=30,
                ping_timeout=10
            ) as websocket:
                self.logger.info("✅ Infura WebSocket连接成功!")
                
                # 发送测试订阅
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["newPendingTransactions"]
                }
                
                await websocket.send(json.dumps(subscribe_msg))
                self.logger.info("已发送订阅请求")
                
                # 等待响应
                response = await asyncio.wait_for(websocket.recv(), timeout=10)
                self.logger.info(f"收到响应: {response}")
                
                # 保持连接一段时间来测试稳定性
                self.logger.info("测试连接稳定性...")
                for i in range(5):  # 测试5次接收
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5)
                        self.logger.info(f"✅ 收到消息 {i+1}/5: {message[:100]}...")
                    except asyncio.TimeoutError:
                        self.logger.info(f"⏳ 等待消息 {i+1}/5 超时（正常）")
                    
                    await asyncio.sleep(1)
                
                self.logger.info("🎉 Infura WebSocket测试完全成功！")
                return True
                
        except asyncio.TimeoutError:
            self.logger.error("❌ 连接超时 - Infura节点响应慢或不可用")
            return False
        except Exception as e:
            self.logger.error(f"❌ Infura WebSocket连接失败: {str(e)}")
            return False

    async def start_listening(self):
        """开始监听 - 测试版本"""
        self.is_running = True
        self.logger.info("开始WebSocket连接测试...")
        
        # 测试Infura连接
        success = await self.test_infura_connection()
        
        if success:
            self.logger.info("✅ 测试结果: Infura在Render上可以工作！")
        else:
            self.logger.info("❌ 测试结果: Infura在Render上无法工作")
        
        # 保持服务运行但不做其他事
        while self.is_running:
            await asyncio.sleep(1)

    async def stop_listening(self):
        """停止监听"""
        self.is_running = False
        self.logger.info("测试结束")
