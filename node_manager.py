import asyncio
import logging
import os
from typing import Dict, List, Optional
import json
from urllib.parse import urlparse

import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from web3 import Web3, WebsocketProvider, HTTPProvider
from web3.exceptions import TimeExhausted, TransactionNotFound
from web3.middleware import geth_poa_middleware


class NodeManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.current_node_index = 0
        self.http_nodes = []
        self.ws_nodes = []


        # 🆕 Redis 客户端（用于节点状态缓存）
        self.redis_client: Optional[redis.Redis] = None
        self.redis_key = "node_manager:healthy_nodes"


        # 🆕 WebSocket 订阅管理
        self.websocket: Optional[Web3] = None
        self.subscriptions = {}  # 存储订阅ID与回调函数
        self._reconnect_task: Optional[asyncio.Task] = None


        # 🆕 Infura 节点管理
        self.infura_ws_url = None
        self.infura_http_url = None
        self._setup_infura_node()


        # 🆕 动态配置
        self.dynamic_nodes_url = os.getenv("NODES_CONFIG_URL")  # 支持从远程 URL 获取节点配置
        self._init_nodes()


    def _setup_infura_node(self):
        """设置 Infura 节点"""
        infura_ws_url = os.getenv('INFURA_BSC_WS_URL')
        infura_http_url = os.getenv('INFURA_BSC_HTTP_URL')
        
        if infura_ws_url:
            self.infura_ws_url = infura_ws_url
            self.logger.info(f"✅ Infura WebSocket 节点配置成功: {infura_ws_url[:50]}...")
        else:
            self.logger.warning("⚠️ 未找到 INFURA_BSC_WS_URL 环境变量")
            
        if infura_http_url:
            self.infura_http_url = infura_http_url
            self.logger.info(f"✅ Infura HTTP 节点配置成功: {infura_http_url[:50]}...")
        else:
            self.logger.warning("⚠️ 未找到 INFURA_BSC_HTTP_URL 环境变量")


    def _extract_node_name(self, url):
        """✅ 新增：从URL中提取节点名称"""
        try:
            if 'infura' in url:
                return 'Infura'
            elif 'ninicoin' in url:
                return 'NiniCoin'
            elif 'binance.org' in url:
                return 'Binance'
            elif 'defibit' in url:
                return 'DeFiBit'
            else:
                # 提取域名部分作为名称
                parsed = urlparse(url)
                return parsed.netloc.split('.')[-2] if '.' in parsed.netloc else parsed.netloc
        except:
            return 'Unknown'


    def _init_nodes(self):
        """初始化节点连接，支持动态配置"""
        # 优先使用 Infura HTTP 节点
        if self.infura_http_url:
            try:
                w3 = Web3(HTTPProvider(self.infura_http_url, request_kwargs={'timeout': 10}))
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                if w3.is_connected():
                    # ✅ 修改：为节点添加名称标识
                    self.http_nodes.append({
                        'url': self.infura_http_url,
                        'w3': w3,
                        'healthy': True,
                        'infura': True,
                        'name': 'Infura'  # ✅ 新增：节点名称
                    })
                    self.logger.info(f"✅ 成功连接 Infura HTTP 节点")
                else:
                    self.logger.warning(f"❌ 无法连接 Infura HTTP 节点")
            except Exception as e:
                self.logger.error(f"❌ 连接 Infura HTTP 节点失败: {e}")


        # 初始化其他 HTTP 节点 - 使用硬编码的节点列表
        for node_url in self.config.BSC_NODES:
            if node_url:
                try:
                    w3 = Web3(HTTPProvider(node_url, request_kwargs={'timeout': 10}))
                    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                    if w3.is_connected():
                        # ✅ 修改：为节点添加名称标识
                        node_name = self._extract_node_name(node_url)
                        self.http_nodes.append({
                            'url': node_url,
                            'w3': w3,
                            'healthy': True,
                            'infura': False,
                            'name': node_name  # ✅ 新增：节点名称
                        })
                        self.logger.info(f"✅ 成功连接 HTTP 节点: {node_url}")
                    else:
                        self.logger.warning(f"❌ 无法连接 HTTP 节点: {node_url}")
                except Exception as e:
                    self.logger.error(f"❌ 连接 HTTP 节点失败 {node_url}: {e}")


        # 初始化 WebSocket 节点 - 优先 Infura
        ws_nodes = []
        
        # 优先添加 Infura WebSocket
        if self.infura_ws_url:
            ws_nodes.append({
                'url': self.infura_ws_url, 
                'healthy': True, 
                'infura': True,
                'name': 'Infura'  # ✅ 新增：节点名称
            })
        
        # 添加其他备用 WebSocket 节点
        preferred_ws_nodes = [
            "wss://bsc-ws-node.nariox.org",
            "wss://bsc.publicnode.com",
            "wss://ws-bsc.nodeinfra.com",
            "wss://bsc-rpc.publicnode.com"
        ]
        for url in preferred_ws_nodes:
            node_name = self._extract_node_name(url)
            ws_nodes.append({
                'url': url, 
                'healthy': True, 
                'infura': False,
                'name': node_name  # ✅ 新增：节点名称
            })
            
        self.ws_nodes = ws_nodes
        
        for node in self.ws_nodes:
            node_type = "Infura" if node['infura'] else "备用"
            self.logger.info(f"🌐 注册 {node_type} WebSocket 节点: {node['url']}")


    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        retry=retry_if_exception_type((TimeoutError, ConnectionError))
    )
    async def make_http_request(self, method, *args, **kwargs):
        """使用重试机制发送 HTTP 请求 - 优先使用 Infura 节点"""
        # 首先尝试 Infura 节点
        infura_nodes = [node for node in self.http_nodes if node.get('infura') and node['healthy']]
        if infura_nodes:
            try:
                node = infura_nodes[0]
                w3 = node['w3']
                result = self._call_w3_method(w3, method, *args, **kwargs)
                node['healthy'] = True
                self.current_node_index = self.http_nodes.index(node)
                return result
            except Exception as e:
                self.logger.warning(f"⚠️ Infura 节点请求失败: {e}")
                infura_nodes[0]['healthy'] = False


        # 回退到其他节点
        for i in range(len(self.http_nodes)):
            node_index = (self.current_node_index + i) % len(self.http_nodes)
            node = self.http_nodes[node_index]
            if not node['healthy'] or node.get('infura'):
                continue
            try:
                w3 = node['w3']
                result = self._call_w3_method(w3, method, *args, **kwargs)
                node['healthy'] = True
                self.current_node_index = node_index
                return result
            except Exception as e:
                self.logger.warning(f"⚠️ 节点 {node['url']} 请求失败: {e}")
                node['healthy'] = False
                
        raise ConnectionError("所有 HTTP 节点均不可用")
    
    def _call_w3_method(self, w3, method, *args, **kwargs):
        """调用 Web3 方法"""
        if method == 'eth_call':
            return w3.eth.call(*args, **kwargs)
        elif method == 'get_transaction':
            return w3.eth.get_transaction(*args, **kwargs)
        elif method == 'get_code':
            return w3.eth.get_code(*args, **kwargs)
        elif method == 'get_block':
            return w3.eth.get_block(*args, **kwargs)
        else:
            raise ValueError(f"未知的 HTTP 方法: {method}")


    async def _test_websocket_connection(self, ws_url: str) -> bool:
        """异步测试 WebSocket 连接"""
        try:
            w3 = Web3(WebsocketProvider(ws_url, websocket_kwargs={'timeout': 15}))
            # 使用线程池执行同步的 is_connected
            is_connected = await asyncio.get_event_loop().run_in_executor(None, w3.is_connected)
            if is_connected:
                self.websocket = w3  # 保存可用的 WebSocket 连接
                return True
            return False
        except Exception as e:
            self.logger.debug(f"WebSocket 连接测试失败 {ws_url}: {e}")
            return False


    async def get_current_websocket_url(self) -> str:
        """获取当前可用的 WebSocket 节点 URL - 优先使用 Infura"""
        # 强制优先使用 Infura WebSocket 节点
        if self.infura_ws_url:
            self.logger.info(f"🎯 优先使用 Infura WebSocket 节点: {self.infura_ws_url[:50]}...")
            if await self._test_websocket_connection(self.infura_ws_url):
                self.logger.info("✅ Infura WebSocket 节点连接成功")
                return self.infura_ws_url
            else:
                self.logger.warning("❌ Infura WebSocket 节点连接失败，尝试备用节点")


        # 测试并选择其他可用节点
        for node in self.ws_nodes:
            if node.get('infura'):  # 跳过 Infura，已经尝试过了
                continue
                
            ws_url = node['url']
            if node['healthy'] and await self._test_websocket_connection(ws_url):
                self.logger.info(f"✅ 使用备用 WebSocket 节点: {ws_url}")
                return ws_url


        raise ConnectionError("所有 WebSocket 节点均不可用")


    async def _auto_reconnect(self):
        """自动重连 WebSocket"""
        while True:
            try:
                if not self.websocket or not await asyncio.get_event_loop().run_in_executor(None, self.websocket.is_connected):
                    self.logger.warning("WebSocket 连接断开，正在尝试重连...")
                    await self.get_current_websocket_url()  # 重新获取连接
                    # 恢复订阅
                    await self._resubscribe()
                await asyncio.sleep(5)  # 每 5 秒检查一次
            except Exception as e:
                self.logger.error(f"WebSocket 重连失败: {e}")
                await asyncio.sleep(10)


    async def _resubscribe(self):
        """恢复所有订阅"""
        if not self.websocket:
            return
        for event_type, callback in self.subscriptions.items():
            try:
                # 🆕 这里需要根据实际订阅类型实现重新订阅逻辑
                # 例如：self.websocket.eth.subscribe(event_type, callback)
                pass
            except Exception as e:
                self.logger.error(f"重新订阅 {event_type} 失败: {e}")


    def mark_websocket_unhealthy(self, url: str):
        """标记 WebSocket 节点不健康"""
        if self.infura_ws_url and url == self.infura_ws_url:
            self.logger.warning(f"⚠️ 标记 Infura 节点为不健康: {url}")
            return
        for node in self.ws_nodes:
            if node['url'] == url:
                node['healthy'] = False
                self.logger.warning(f"⚠️ 标记 WebSocket 节点为不健康: {url}")
                # 清除 Redis 缓存
                if self.redis_client:
                    asyncio.create_task(self.redis_client.delete(self.redis_key))
                break


    async def check_node_health(self):
        """定期检查节点健康状态"""
        # 检查 HTTP 节点
        for node in self.http_nodes:
            try:
                is_connected = await asyncio.get_event_loop().run_in_executor(None, node['w3'].is_connected)
                node['healthy'] = is_connected
            except:
                node['healthy'] = False


    async def start(self):
        """启动 NodeManager（初始化 Redis 和自动重连）"""
        # 初始化 Redis 客户端
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)


        # 启动自动重连任务
        self._reconnect_task = asyncio.create_task(self._auto_reconnect())


    async def close(self):
        """✅ 修复：安全关闭 NodeManager"""
        try:
            # 取消重连任务
            if self._reconnect_task:
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass
            
            # 关闭 Redis 客户端
            if self.redis_client:
                await self.redis_client.close()
                
            # 关闭 WebSocket 连接
            if self.websocket:
                try:
                    # 更安全的关闭方式
                    if hasattr(self.websocket, 'provider') and self.websocket.provider:
                        # 对于Web3的WebSocketProvider，直接设置为None
                        self.websocket.provider = None
                except Exception as e:
                    self.logger.warning(f"关闭WebSocket时出错: {e}")
                    
            self.logger.info("✅ NodeManager 已安全关闭")
        except Exception as e:
            self.logger.error(f"关闭NodeManager时出错: {e}")
