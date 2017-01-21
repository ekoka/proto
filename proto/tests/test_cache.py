import unittest
from collections import OrderedDict, namedtuple
from datetime import datetime, date, time
from decimal import Decimal
import json 

from .cache import (
    params_snapshot, 
    make_hash,
    RedisStore,
    JsonCache,
)

class CacheTest(unittest.TestCase):
    def test_params_snapshot(self):
        d1 = dict(a=[1, 2, 3], b=dict(b=[1,2,3], c='abc', e=list('cba')), c=3)
        d2 = dict(a=[2, 3, 1], b=dict(b=[3,2,1], c='abc', e=list('abc')), c=3)
        d3 = dict(a=[1, 2, 3], b=dict(b=[1,2,3], c='cba', e=list('cba')), c=3)

        self.assertEqual(make_hash(params_snapshot(d1)), 
                         make_hash(params_snapshot(d2)))

        self.assertNotEqual(make_hash(params_snapshot(d1)), 
                            make_hash(params_snapshot(d3)))

    def test_can_instantiate_redis_store(self):
        config = dict(
            namespace='test',
            host=None, 
            port=None, 
            db=None,
        )
        redis = RedisStore(**config)
        self.assertEqual(redis.server.config_get('port')['port'], '6379')

    
    def test_can_cache_response(self):
        redis_config = dict(
            namespace='test',
            host=None, 
            port=None, 
            db=None,
        )
        cache = JsonCache(redis_config=redis_config)

        Response = namedtuple(
            'Response', ['data', 'etag', 'last_modified'])
        response = Response(
            data=str(dict(firstname=u'mike', email=u'test@example.org')),
            etag='testtest1234',
            last_modified=datetime.now(),)

        path = '/cache/path/test'
        params = dict(key1=2, key2='abc', key3=[1,2,3,'a','b','c'])
        role = 'admin'
        cache.store(response, '/cache/path/test', params, role)

        key = cache._make_key(path=path, params=params, role=role)
        cached_resource = cache.redis.get_resource(key)
        self.assertEqual(cached_resource['data'], response.data)
        self.assertEqual(cached_resource['etag'], response.etag)



