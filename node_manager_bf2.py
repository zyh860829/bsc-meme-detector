import asyncio
import aiohttp
import logging
import os  # 🆕 添加os导入
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from web3 import Web3, WebsocketProvider, HTTPProvider
from web3.exceptions import TimeExhausted, TransactionNotFound

class NodeManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.current_node_index = 0
        self.current_ws_node_index = 0
        self.http_nodes = []
        self.ws_nodes = []
        
        # 🆕 添加Infura节点管理
        self.infura_ws_url = None
        self._setup_infura_node()
        
        self._init_nodes()
    
    def _setup_infura_node(self):
        """设置Infura节点"""
        infura_url = os.getenv('INFURA_BSC_WS_URL')
        
        if infura_url:
            self.infura_ws_url = infura_url
            self.logger.info(f"✅ Infura节点配置成功: {infura_url[:50]}...")
        else:
            self.logger.warning("⚠️ 未找到INFURA_BSC_WS_URL环境变量，将使用免费节点")
    
    def _init_nodes(self):
        """初始化节点连接"""
        for node_url in self.config.BSC_NODES:
            if node_url:
                try:
                    w3 = Web3(HTTPProvider(node_url))
                    if w3.is_connected():
                        self.http_nodes.append({
                            'url': node_url,
                            'w3': w3,
                            'healthy': True
                        })
                        self.logger.info(f"成功连接HTTP节点: {node_url}")
                except Exception as e:
                    self.logger.error(f"连接HTTP节点失败 {node_url}: {e}")
        
        for ws_url in self.config.BSC_WS_NODES:
            if ws_url:
                self.ws_nodes.append({
                    'url': ws_url,
                    'healthy': True
                })
                self.logger.info(f"注册WS节点: {ws_url}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        retry=retry_if_exception_type((TimeoutError, ConnectionError))
    )
    async def make_http_request(self, method, *args, **kwargs):
        """使用重试机制发送HTTP请求"""
        for i in range(len(self.http_nodes)):
            node_index = (self.current_node_index + i) % len(self.http_nodes)
            node = self.http_nodes[node_index]
            
            if not node['healthy']:
                continue
                
            try:
                if method == 'eth_call':
                    result = node['w3'].eth.call(*args, **kwargs)
                elif method == 'get_transaction':
                    result = node['w3'].eth.get_transaction(*args, **kwargs)
                elif method == 'get_code':
                    result = node['w3'].eth.get_code(*args, **kwargs)
                elif method == 'get_block':
                    result = node['w3'].eth.get_block(*args, **kwargs)
                else:
                    raise ValueError(f"未知的HTTP方法: {method}")
                
                # 请求成功，标记节点健康
                node['healthy'] = True
                self.current_node_index = node_index
                return result
                
            except Exception as e:
                self.logger.warning(f"节点 {node['url']} 请求失败: {e}")
                node['healthy'] = False
                continue
        
        raise ConnectionError("所有HTTP节点均不可用")
    
    def get_current_websocket_url(self):
        """获取当前可用的WebSocket节点URL"""
        # 🆕 优先返回Infura节点
        if self.infura_ws_url:
            self.logger.info("🎯 使用Infura WebSocket节点")
            return self.infura_ws_url
        
        # 🆕 如果Infura不可用，回退到免费节点
        for i in range(len(self.ws_nodes)):
            node_index = (self.current_ws_node_index + i) % len(self.ws_nodes)
            node = self.ws_nodes[node_index]
            
            if node['healthy']:
                self.current_ws_node_index = node_index
                self.logger.info(f"🆓 使用免费WebSocket节点: {node['url']}")
                return node['url']
        
        raise ConnectionError("所有WebSocket节点均不可用")
    
    def mark_websocket_unhealthy(self, url):
        """标记WebSocket节点不健康"""
        # 🆕 如果是Infura节点，需要特殊处理
        if self.infura_ws_url and url == self.infura_ws_url:
            self.logger.warning(f"标记Infura节点为不健康: {url}")
            # 可以选择临时禁用Infura，回退到免费节点
            # self.infura_ws_url = None  # 取消注释这行来禁用Infura
            return
        
        # 原有的免费节点标记逻辑
        for node in self.ws_nodes:
            if node['url'] == url:
                node['healthy'] = False
                self.logger.warning(f"标记WebSocket节点为不健康: {url}")
                break
    
    async def check_node_health(self):
        """定期检查节点健康状态"""
        # 检查HTTP节点
        for node in self.http_nodes:
            try:
                if node['w3'].is_connected():
                    node['healthy'] = True
                else:
                    node['healthy'] = False
            except:
                node['healthy'] = False
        
        # 🆕 可以添加Infura节点健康检查（可选）
        # if self.infura_ws_url:
        #     # 这里可以添加Infura节点的健康检查逻辑
        #     pass
