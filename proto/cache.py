# coding=utf8
from hashlib import sha1
import time

import json
import redis

def params_snapshot(o):
    """
    The purpose of this function is to provide a view of parameters that can
    be frozen, reconstituting dicts and multidicts into the simpler lists and
    tuples structures. An example use case is the need to generate a cache key
    based on params passed via url. It should preferably be used when the
    ordering of parameters has no impact on the outcome of the request, that
    is an operation should be idempotent given the same parameters regardless of their ordering.
    """
    # ordering sets, lists, tuples
    if isinstance(o, (list, tuple, set)):
        return sorted(params_snapshot(e) for e in o)

    # returning data types other than dicts
    if not isinstance(o, dict):
        return o

    # ordering multidicts
    t = type(o)
    try:
        ordered_dict = t((k, i) for k,v in o.iterlists()
                                for i in params_snapshot(v))
        get_value = t.getlist
    except AttributeError:
        ordered_dict = t((k, params_snapshot(v)) for k,v in o.iteritems())
        get_value = t.get

    return [(k, get_value(ordered_dict, k)) for k in sorted(ordered_dict)]

def make_hash(o):
    # hashing sets, tuples and lists
    if isinstance(o, (set, tuple, list)):
        return sha1(repr(tuple([make_hash(e) for e in o]))).hexdigest()

    # hashing other data types except dicts 
    if not isinstance(o, dict):
        return sha1(repr(o)).hexdigest()

    # hashing dicts
    new_o = dict()
    for k,v in o.items():
        new_o[k] = make_hash(v)
    return sha1(repr(tuple(frozenset(new_o.items())))).hexdigest()

class JsonResponseCache(object):

    def __init__(self, redis_config):
        self.store = RedisStore(**redis_config)

    def _make_key(self, path, params=None, role=None):
        key = [path]
        if role:
            key.append(role)
        if params:
            hashed_params = make_hash(params_snapshot(params))
            if hashed_params:
                key.append(hashed_params)
        return ':'.join(key)

    def store_resource(self, key_params, resource):
        key = self._make_key(**key_params)
        self.store.set_resource(key, resource)
        return True

    def store_response(self, request, response, role=None):
        key_params = dict(
            path = request.path,
            params = request.params,
            role=role,
        )
        response_cache = dict(
            result=response.context.get('result'),
            data=response.data,
            path=request.path,
            role=role or '',
            etag=response.etag,
            #timestamp=time.mktime(response.last_modified.timetuple()),
            timestamp=response.last_modified,
            params=request.params,
            # NOTE: try these in case we have problems with the above
            #params=json.dumps(request.params),
            #params=json.dumps(params_snapshot(request.params)),
        )
        #self.store.set_resource(key, response_cache)
        return self.store_resource(key_params, response_cache)

    def load_response(self, request, role=None):
        path = request.path
        params = request.params
        key = self._make_key(path, params, role)
        return self.store.get_resource(key)

    def load_all_responses(self, request, role=None):
        key = self._make_key(path, role=role)
        pattern = key + '*'
        return self.get_all_resources_from_pattern(pattern)

    def get_timestamp(self):
        dt = datetime.datetime.utcnow()
        return time.mktime(dt.timetuple())

class RedisStore(object):

    def __init__(self, namespace, host=None, port=None, db=None):
        self.namespace = namespace
        self.template = "{namespace}:{{key}}".format(namespace=self.namespace)

        """
        NOTE: in the template the `key` is the portion of the redis id 
        that specifically targets the resource. it can be comprised of 
        additional inner elements to more precisely direct the retrieval 
        of a resource. For example a resource may have different formats
        depending on user provided parameters.
        e.g. a key containing role and a hash of params:
        key = "/path/to/my/resource:admin:b219f8e3a39e40b9c8fd73"

        That single resource can then be spread across multiple records which
        is where the `field` comes into play to narrow which part of the data
        is being sought.
        """
         
        if host is None:
            host = 'localhost'
        if port is None:
            port = 6379 
        if db is None:
            db = 0
        self.server = redis.StrictRedis(host, port=port, db=db)

    def get_resource(self, key):
        hkey = self.template.format(key=key)
        return self.server.hgetall(hkey)

    def get_all_resources_from_pattern(self, pattern, fields=None):
        # get all data
        keys = self.scan_keys(pattern)
        rv = dict((k, self.server.hgetall(k)) for k in keys)
        return rv

    def scan_keys(self, pattern):
        """
        We fetch all keys that match the pattern.
        """
        rv = set()
        cursor = 0
        count = 10000
        match = self.template.format(key=pattern)
        while True:
            # redis-cli SCAN cursor MATCH match COUNT count
            cursor, keys = self.server.scan(cursor, match=match, count=count)
            rv = rv.union(keys)
            # if full iteration, end the loop
            if cursor==0:
                break
        return rv

    def set_resource(self, key, data):
        hkey = self.template.format(key=key)
        # redis-cli HMSET key field value [field value...]
        return self.server.hmset(hkey, data)

    def delete_from_pattern(self, pattern):
        keys = self.scan_keys(pattern=pattern)
        for k in keys:
            self.delete(k)

    def delete(self, key):
        self.server.delete(key)

    def get_set(self, key, field):
        key = self.template.format(key=key, field=field)
        return self.server.smembers(key)

    def add_to_set(self, key, field, value):
        key = self.template.format(key=key, field=field)
        self.server.sadd(key, value)
