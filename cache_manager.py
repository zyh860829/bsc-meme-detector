import redis
import json
import pickle
import logging
from datetime import timedelta

class CacheManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        try:
            self.redis_client = redis.from_url(config.REDIS_URL)
            self.redis_client.ping()
            self.logger.info("Redis连接成功")
        except Exception as e:
            self.logger.error(f"Redis连接失败: {e}")
            self.redis_client = None
    
    def get_key(self, category, identifier):
        """生成缓存键"""
        return f"meme_detector:{category}:{identifier}"
    
    def set(self, category, identifier, data, ttl=None):
        """设置缓存"""
        if not self.redis_client:
            return False
            
        try:
            key = self.get_key(category, identifier)
            if ttl:
                self.redis_client.setex(key, timedelta(seconds=ttl), pickle.dumps(data))
            else:
                self.redis_client.set(key, pickle.dumps(data))
            return True
        except Exception as e:
            self.logger.error(f"缓存设置失败: {e}")
            return False
    
    def get(self, category, identifier):
        """获取缓存"""
        if not self.redis_client:
            return None
            
        try:
            key = self.get_key(category, identifier)
            data = self.redis_client.get(key)
            return pickle.loads(data) if data else None
        except Exception as e:
            self.logger.error(f"缓存获取失败: {e}")
            return None
    
    def delete(self, category, identifier):
        """删除缓存"""
        if not self.redis_client:
            return False
            
        try:
            key = self.get_key(category, identifier)
            self.redis_client.delete(key)
            return True
        except Exception as e:
            self.logger.error(f"缓存删除失败: {e}")
            return False
    
    def exists(self, category, identifier):
        """检查缓存是否存在"""
        if not self.redis_client:
            return False
            
        try:
            key = self.get_key(category, identifier)
            return self.redis_client.exists(key) > 0
        except Exception as e:
            self.logger.error(f"缓存检查失败: {e}")
            return False
