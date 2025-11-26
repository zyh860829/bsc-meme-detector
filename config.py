import os
from dotenv import load_dotenv


load_dotenv()


class Config:
    # 服务监听端口（Render 会自动设置 PORT 环境变量）
    PORT = os.getenv("PORT", "8080")


    # BSC节点配置 - 硬编码的节点列表，按响应速度排序
    BSC_NODES = [
        'https://bsc-dataseed4.ninicoin.io/',   # 237ms 🥇
        'https://bsc-dataseed3.ninicoin.io/',   # 238ms 🥈
        'https://bsc-dataseed2.binance.org/',   # 1048ms
        'https://bsc-dataseed1.defibit.io/',    # 1112ms
        'https://bsc-dataseed2.ninicoin.io/',   # 备用节点
        'https://bsc-dataseed.binance.org/',    # 备用节点
        'https://bsc-dataseed1.ninicoin.io/',   # 备用节点
        'https://bsc-dataseed3.binance.org/',   # 备用节点
        'https://bsc-dataseed3.defibit.io/',
        'https://bsc-dataseed4.defibit.io/',
        'https://bsc-mainnet.public.blastapi.io',
        'https://bsc.rpc.blxrbdn.com/',
        'https://binance.llamarpc.com',
        'https://bsc.meowrpc.com',
        'https://bsc-dataseed2.defibit.io/',    # 备用节点
        'https://bsc-dataseed1.ninicoin.io/'    # 备用节点
    ]
    
    BSC_WS_NODES = [
        os.getenv('BSC_WS_1'),
        os.getenv('BSC_WS_2'),
        os.getenv('BSC_WS_3'),
        os.getenv('BSC_WS_4'),
        os.getenv('QUICKNODE_WS'),
        os.getenv('MORALIS_WS')
    ]
    
    # API密钥
    BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY')
    TOKENSNIFFER_API_KEY = os.getenv('TOKENSNIFFER_API_KEY')
    DEXSCREENER_API_KEY = os.getenv('DEXSCREENER_API_KEY')
    
    # 通知配置
    DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK')
    DINGTALK_SECRET = os.getenv('DINGTALK_SECRET')
    
    # Redis配置
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # 系统配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    NODE_TIMEOUT = 3
    DETECTION_TIMEOUT = 8
    CACHE_TTL_STATIC = 3600  # 1小时
    CACHE_TTL_DYNAMIC = 30   # 30秒
    
    # 风险阈值
    MIN_LIQUIDITY_USD = 10000
    MIN_LOCK_DAYS = 30
    MIN_LOCK_RATIO = 0.9
    MAX_TAX_RATE = 0.08
    MAX_PREMINE_RATIO = 0.1
    MAX_PRESALE_RATIO = 0.2
    
    # PancakeSwap Factory地址
    PANCAKE_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    PANCAKE_FACTORY_ABI = [
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "name": "token0", "type": "address"},
                {"indexed": True, "name": "token1", "type": "address"},
                {"indexed": False, "name": "pair", "type": "address"},
                {"indexed": False, "name": "", "type": "uint256"}
            ],
            "name": "PairCreated",
            "type": "event"
        }
    ]

    # ✅ 新增：环境变量验证方法
    def validate_required_vars(self):
        """验证必要环境变量"""
        required = {
            'DINGTALK_WEBHOOK': self.DINGTALK_WEBHOOK,
            'REDIS_URL': self.REDIS_URL
        }
        missing = [var for var, value in required.items() if not value]
        if missing:
            raise ValueError(f"缺少必要环境变量: {missing}")
        return True
    
    # ✅ 新增：获取有效的WebSocket节点
    def get_ws_nodes(self):
        """获取有效的WebSocket节点"""
        env_nodes = [node for node in self.BSC_WS_NODES if node]
        # 如果没有环境变量节点，使用备用节点
        if not env_nodes:
            return [
                "wss://bsc-ws-node.nariox.org",
                "wss://bsc.publicnode.com", 
                "wss://ws-bsc.nodeinfra.com"
            ]
        return env_nodes
