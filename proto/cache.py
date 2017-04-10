# coding=utf8
from hashlib import sha1
import time
import redis

from proto._compat import isiterable

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

class ResponseCache(object):

    def __init__(self, store):
        self.store = store

    def make_key(self, path, params=None, role=None):
        # returns `path` unmodified if `params` and `role` are empty 
        key = [path]
        if role:
            key.append(role)
        if params:
            hashed_params = make_hash(params_snapshot(params))
            if hashed_params:
                key.append(hashed_params)
        return ':'.join(key)

    #def store_resource(self, key, resource, data_type=None):
    #    return True

    def store_response(self, path, response, params=None, role=None):
        key_parts = dict(path = path, params = params, role=role)
        key = self.make_key(**key_parts)
        response_cache = dict(
            result=response.context.get('result'),
            data=response.data,
            path=path,
            role=role or '',
            etag=response.etag,
            #timestamp=time.mktime(response.last_modified.timetuple()),
            timestamp=response.last_modified,
            params=params,
            # NOTE: try these in case we have problems with the above
            #params=json.dumps(request.params),
            #params=json.dumps(params_snapshot(request.params)),
        )
        return self.store.set_hash(key, response_cache, data_type='response')
        #return self.store_resource(key, response_cache, data_type='response')

    def delete_response(self, path, params=None, role=None):
        key_parts = dict(path=path, params=params, role=role)
        key = self.make_key(**key_parts)
        self.store.delete(key, data_type='response')
        dependents = self.find_dependents(key)
        for d in dependents:
            self.delete_response(d)
            self.drop_dependencies(d)


    def register_dependencies(self, dependent_params, dependencies):
        if not (dependent_params or dependencies):
            return
        if not isiterable(dependencies, exclude_dict=True):
            dependencies = [dependencies]
        key = self.make_key(**dependent_params)
        for params in dependencies:
            dependency = self.make_key(**params)
            self.store.add_to_set(dependency, key, data_type='dependents')
            self.store.add_to_set(key, dependency, data_type='dependencies')

    def drop_dependencies(self, path, params=None, role=None):
        key = self.make_key(path=path, params=params, role=role)
        dependencies = self.store.get_data(key, data_type='dependencies')
        for d in dependencies:
            self.store.pop_set(d, key, data_type='dependents')
        self.store.empty_set(key, data_type='dependencies')

    def find_dependents(self, path, params=None, role=None):
        key = self.make_key(path=path, params=params, role=role)
        return self.store.get_data(key, data_type='dependents')

    def load_response(self, path, params=None, role=None):
        key = self.make_key(path=path, params=params, role=role)
        return self.store.get_data(key, data_type='response')

    def load_all_responses(self, request, role=None):
        key = self.make_key(path, role=role)
        pattern = key + '*'
        return self.store.get_all_data_from_pattern(
            pattern, data_type='response')

    def get_timestamp(self):
        dt = datetime.datetime.utcnow()
        return time.mktime(dt.timetuple())

class RedisStore(object):

    def __init__(self, namespace, host=None, port=None, db=None):
        self.namespace = namespace
        self.template = namespace + ":{data_type}:{key}"

        """
        NOTE: In the redis template above: 
        - The `namespace` identifies the database. It's analogous to a db name
        when connecting to an RDBMS.
        - The `data_type` steers the storage toward a type of resource. To
        continue with our analogy this would be a table name.
        - The `key` is the portion of the redis id 
        that specifically targets the resource. it can be comprised of 
        additional inner elements to more precisely direct the retrieval 
        of a resource. For example a resource may have different formats
        depending on user provided parameters.
        e.g. a key containing role and a hash of params:
        key = "/path/to/my/resource:admin:b219f8e3a39e40b9c8fd73"
        This would be the ID of a resource.

        That single resource can then be spread across multiple records which
        is where the `field` comes into play to narrow which part of the data
        is being sought.
        """

        self.value_types = ('value',)
        self.hash_types = ('hash', 'response')
        self.set_types = ('set', 'dependencies', 'dependents')
        self.default_data_type = 'value'
        self.default_set_type = 'set'
        self.default_hash_type = 'hash'
         
        if host is None:
            host = 'localhost'
        if port is None:
            port = 6379 
        if db is None:
            db = 0

        self.server = redis.StrictRedis(host, port=port, db=db)

    def check_data_type(self, data_type):
        supported = (self.value_types + self.hash_types + self.set_types)
        if data_type not in supported:
            #TODO raise a custom Error here
            raise Exception('The provided namespaced key is not supported')

    def base_key(self, namespaced_key, data_type):
        self.check_data_type(data_type)
        key = namespaced_key.partition(self.namespace)
        data_type += ':'
        key = key.partition(data_type)

    def key(self, key, data_type=None):
        if not data_type:
            data_type = self.default_data_type
        self.check_data_type(data_type)
        return self.template.format(key=key, data_type=data_type)

    def get_data(self, key, data_type=None):
        if data_type is None:
            data_type = self.default_data_type
        self.check_data_type(data_type)

        key = self.key(key, data_type)
        if data_type in self.value_types: 
            rv = self.server.get(key)
        elif data_type in self.hash_types:
            rv = self.server.hgetall(key)
        elif data_type in self.set_types:
            page, rv = self.server.sscan(key)
        return rv

    def get_all_data_from_pattern(self, pattern, data_type=None):
        keys = self.scan_keys(pattern, data_type=data_type)
        rv = dict((k, self.server.hgetall(k)) for k in keys)
        return rv

    def scan_keys(self, pattern, data_type=None):
        # fetch all keys that match glob-style pattern.
        rv = set()
        cursor = 0
        count = 10000
        match = self.key(pattern, data_type)
        while True:
            # redis-cli> SCAN cursor MATCH match COUNT count
            cursor, keys = self.server.scan(cursor, match=match, count=count)
            rv = rv.union(keys)
            # if full iteration, end the loop
            if cursor==0:
                break
        return rv
    
    def add_to_set(self, key, value, data_type=None):
        if not data_type:
            data_type = self.default_set_type
        key = self.key(key, data_type)
        self.server.sadd(key, value)

    def empty_set(self, key, data_type=None):
        if not data_type:
            data_type = self.default_set_type
        key = self.key(key, data_type)
        while self.server.spop(key): pass

    def pop_set(self, key, value, data_type=None):
        if not data_type:
            data_type = self.default_set_type
        key = self.key(key, data_type)
        self.server.srem(key, value)

    def set_hash(self, key, data, data_type=None):
        if not data_type:
            data_type = self.default_hash_type
        key = self.key(key, data_type)
        # redis-cli HMSET key field value [field value...]
        return self.server.hmset(key, data)

    def delete_all(self, pattern, data_type=None):
        if not data_type:
            data_type = '*'

        keys = self.scan_keys(pattern=pattern, data_type=data_type)
        for k in keys:
            self.server.delete(key)

    def delete(self, key, data_type=None):
        if not data_type:
            data_type = '*'
        key = self.key(key, data_type)
        self.server.delete(key)
