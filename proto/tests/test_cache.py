import unittest
from collections import OrderedDict, namedtuple
from datetime import datetime, date, time
from decimal import Decimal
import json 

from proto.cache import (
    params_snapshot, 
    make_hash,
    RedisStore,
    JsonResponseCache,
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

    
    def _make_request_response(self):
        Response = namedtuple('Response', ['data', 'etag', 'last_modified'])
        response = Response(
            data=str(dict(firstname=u'mike', email=u'test@example.org')),
            etag='testtest1234',
            last_modified=datetime.now(),
        )

        Request = namedtuple('Request', ['path', 'params'])
        request = Request(
            path='/cache/path/test',
            params=dict(key1=2, key2='abc', key3=[1,2,3,'a','b','c']),
        )

        return request, response

    def test_can_cache_response(self):
        redis_config = dict(
            namespace='test',
            host=None, 
            port=None, 
            db=None,
        )
        cache = JsonResponseCache(redis_config=redis_config)

        # --- mocks
        request, response = self._make_request_response()
        # ---

        cache.store(request, response, role='admin')

        key = cache._make_key(
            path=request.path, params=request.params, role='admin')
        cached_resource = cache.redis.get_resource(key)
        self.assertEqual(cached_resource['data'], response.data)
        self.assertEqual(cached_resource['etag'], response.etag)

        key = cache._make_key(
            path=request.path, params=request.params, role='users')
        cached_resource = cache.redis.get_resource(key)
        self.assertNotEqual(cached_resource.get('data'), response.data)
        self.assertNotEqual(cached_resource.get('etag'), response.etag)



