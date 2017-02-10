import unittest
from collections import OrderedDict, namedtuple
from datetime import datetime, date, time
from decimal import Decimal
import json 
from uuid import uuid4

from proto.cache import (
    params_snapshot, 
    make_hash,
    RedisStore,
    JsonResponseCache,
)

def rndstr():
    return uuid4().hex[:6]

class JsonResponseCacheTest(unittest.TestCase):

    def setUp(self):
        test_namespace = 'test'
        redis_config = dict(
            namespace=test_namespace,
            host=None, 
            port=None, 
            db=0,
        )
        self.cache = JsonResponseCache(redis_config)
        self.store = self.cache.store
        self.server = self.store.server

    def tearDown(self):
        # empty server
        self.server.flushdb()

    def raw_key(self, key_parts, data_type=None):
        key = self.cache.make_key(**key_parts)
        key = self.store.key(key, data_type=data_type)
        return key

    def _make_request_response(self):
        Response = namedtuple('Response', [
            'data', 'etag', 'last_modified', 'context'])
        response = Response(
            data=str(dict(firstname=u'mike', email=u'test@'+rndstr()+'.org')),
            etag=rndstr(),
            last_modified=datetime.now(),
            context={},
        )

        Request = namedtuple('Request', ['path', 'params'])
        request = Request(
            path='/'+rndstr()+'/'+rndstr()+'/cache/path/test',
            params=dict(key1=2, key2='abc', key3=[1,2,3,'a','b','c']),
        )

        return request, response

    def test_params_snapshot(self):
        d1 = dict(a=[1, 2, 3], b=dict(b=[1,2,3], c='abc', e=list('cba')), c=3)
        d2 = dict(a=[2, 3, 1], b=dict(b=[3,2,1], c='abc', e=list('abc')), c=3)
        d3 = dict(a=[1, 2, 3], b=dict(b=[1,2,3], c='cba', e=list('cba')), c=3)

        self.assertEqual(make_hash(params_snapshot(d1)), 
                            make_hash(params_snapshot(d2)))

        self.assertNotEqual(make_hash(params_snapshot(d1)), 
                            make_hash(params_snapshot(d3)))

    def test_make_key(self):
        key_parts = dict(path=rndstr(), params=dict(a=rndstr(), b=rndstr()),
                         role=rndstr())
        key = self.cache.make_key(**key_parts)
        # key must begin with the path and the role
        self.assertTrue(
            key.startswith(key_parts['path']+':'+key_parts['role']+':'))
        # if only a string is passed to `make_key()` it should return
        key2 = self.cache.make_key(key)
        self.assertEqual(key2, key)

    def test_can_instantiate_redis_store(self):
        self.assertEqual(self.server.config_get('port')['port'], '6379')

    def test_store_response(self):

        # --- mocks
        request, response = self._make_request_response()
        role = rndstr()
        # ---

        self.cache.store_response(request.path, response,
                                  params=request.params, role=role)

        key = self.cache.make_key(
            path=request.path, params=request.params, role=role)

        cached_resource = self.store.get_data(key, data_type='response')
        self.assertEqual(cached_resource['data'], response.data)
        self.assertEqual(cached_resource['etag'], response.etag)

        key = self.cache.make_key(
            path=request.path, params=request.params, role='users')

        cached_resource = self.store.get_data(key, data_type='response')
        self.assertNotEqual(cached_resource.get('data'), response.data)
        self.assertNotEqual(cached_resource.get('etag'), response.etag)


    def test_register_dependencies(self):
        depnt = {'path':rndstr()}
        depcies = [{'path':rndstr()}, {'path':rndstr()}]
        dep = {'path': rndstr()}
        
        # registering a list of depcies
        self.cache.register_dependencies(depnt, depcies)
        # registering a single dep as a non iterable 
        self.cache.register_dependencies(depnt, dep)
        depcies.append(dep)

        rkey = self.raw_key(depnt, data_type='dependencies')
        page, dependencies = self.server.sscan(rkey)
        #for d in depcies:
        #self.assertEqual(set(dependencies), set(depcies))

        keys = []
        for d in depcies:
            key = self.cache.make_key(**d)
            rkey = self.raw_key(d, data_type='dependents')
            page, k = self.server.sscan(rkey)
            keys.append(k[0])
            self.assertIn(key, dependencies)
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[1], keys[2])

    def test_drop_dependencies(self):
        depnt = {'path':rndstr()}
        depcies = [{'path':rndstr()}, {'path':rndstr()}, {'path':rndstr()}]

        depnt_rkey = self.raw_key(depnt, data_type='dependencies')
        depnt_key = self.cache.make_key(**depnt)

        self.cache.register_dependencies(depnt, depcies)
        page, dependencies = self.server.sscan(depnt_rkey)
        self.assertEqual(len(dependencies), 3)

        for d in depcies:
            d_rkey = self.raw_key(d, data_type='dependents')
            d_key = self.cache.make_key(**d)
            page, dependents = self.server.sscan(d_rkey)
            self.assertTrue(depnt_key in dependents)
            self.assertTrue(d_key in dependencies)

        self.cache.drop_dependencies(**depnt)
        page, dependencies = self.server.sscan(depnt_rkey)
        self.assertEqual(len(dependencies), 0)
        for d in depcies:
            d_key = self.cache.make_key(**d)
            d_rkey = self.raw_key(d, data_type='dependents')
            page, dependents = self.server.sscan(d_rkey)
            self.assertFalse(depnt_key in dependents)

    def test_find_dependents(self):
        dependency = {'path':rndstr()}
        dependents = [{'path':rndstr()}, {'path':rndstr()}, {'path':rndstr()}]

        dependents_keys = []
        for d in dependents:
            dependents_keys.append(self.cache.make_key(**d))
            self.cache.register_dependencies(d, dependency)

        results = self.cache.find_dependents(**dependency)
        for k in dependents_keys:
            self.assertIn(k, set(results))

#    def test_deleting_resource_deletes_its_dependencts(self):
#        req, resp = self._make_request_response()

    def test_delete_response(self):
        req1, resp1 = self._make_request_response()
        role1 = rndstr()
        req2, resp2 = self._make_request_response()
        role2 = rndstr()
        key1_part = dict(path=req1.path, params=req1.params, role=role1)
        key2_part = dict(path=req2.path, params=req2.params, role=role2)

        # storing both resources
        self.cache.store_response(response=resp1, **key1_part)
        self.cache.store_response(response=resp2, **key2_part)
        key1 = self.cache.make_key(**key1_part)
        key2 = self.cache.make_key(**key2_part)

        # make resource1 a dependency of resource2
        self.cache.register_dependencies(key2_part, key1_part)


        # verify that the resource is present
        cached_resource = self.cache.load_response(**key1_part)
        self.assertEqual(cached_resource['data'], resp1.data)

        # verify both resources are linked through the dependency
        dependents = self.cache.find_dependents(**key1_part)
        self.assertIn(key2, dependents)

        # now deleting the dependency
        self.cache.delete_response(**key1_part)

        # verify cached resource properly deleted
        cached_resource = self.cache.load_response(**key1_part)
        self.assertEqual(cached_resource, {})

        # deleting a dependency should also propagates to deleting its
        # dedependents
        cached = self.cache.load_response(**key2_part)
        dependents = self.cache.find_dependents(**key1_part)
        self.assertEqual(cached, {})
        self.assertEqual(dependents, [])
