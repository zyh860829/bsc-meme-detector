import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # BSC节点配置
    BSC_NODES = [
        os.getenv('BSC_NODE_1'),
        os.getenv('BSC_NODE_2')
    ]
    
    BSC_WS_NODES = [
        os.getenv('BSC_WS_1'),
        os.getenv('BSC_WS_2'),
        os.getenv('QUICKNODE_WS'),
        os.getenv('MORALIS_WS')
    ]
    
    # API密钥
    BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY')
    TOKENSNIFFER_API_KEY = os.getenv('TOKENSNIFFER_API_KEY')
    DEXSCREENER_API_KEY = os.getenv('DEXSCREENER_API_KEY')
    
    # 通知配置
    DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK')
    
    # Redis配置
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # 系统配置
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
