# coding=utf-8
import re
import functools
import simplejson as json
from hashlib import sha1
import redis
import time
import datetime

from flask import request, Response, current_app as app
from werkzeug.wrappers import Request#, Response
from werkzeug.http import quote_etag, unquote_etag
from werkzeug.datastructures import ImmutableMultiDict

from ccaapi import bootstrapper

class CacheError(Exception):
    pass

class Cache(object):

    def __init__(self, store=None):
        if store is None:
            store = RedisCacheStore()
        self.store = store

    def _make_key(self, path, params=None, role=None):
        key = [path]
        if role:
            key += [":", role]
        if params:
            hashed_params = make_hash(ordered_params(params))
            if hashed_params:
                key += [":", hashed_params]
        rv = ''.join(key)
        return rv

    def get_all_resources_from_path(self, path):
        # get all resources
        patterns = [path, "{path}:*".format(path=path)]
        rv = {}
        for p in patterns:
            resources = self.store.get_all_resources_from_pattern(p)
            for key, resource in resources.iteritems():
                for f in ['data', 'params', 'role']:
                    try:
                        resource[f] = json.loads(resource[f])
                        # convert `params` to an ImmutableMultiDict
                        if f=='params':
                            resource[f] = ImmutableMultiDict(resource[f])
                    except KeyError:
                        pass
            rv.update(resources)
        return rv

    def get_resource_key(self, path, params=None, role=None):
        return self._make_key(path, params=params, role=role)

    def delete_resource_from_path(self, path, params=None, role=None):
        key = self._make_key(path, params=params, role=role)
        self.delete_resource_from_key(key)

    def delete_resource_from_key(self, key):
        self.store.delete(key)
            
    def get(self, path, params=None, role=None, etag=None, timestamp=None):
        response = None
        # get resource key from uri
        key = self.get_resource_key(path, params=params, role=role)

        # try to find etag in cache
        
        cached_resource = self.store.get_resource(key) or {}
        cached_data = cached_resource.get('data')
        cached_etag = cached_resource.get('etag')
        try:
            cached_timestamp = datetime.datetime.fromtimestamp(
                float(cached_resource['timestamp']))
        except:
            cached_timestamp = None

        # if not deactivated and cached_etag:
        if timestamp and cached_timestamp and timestamp>=cached_timestamp:
            response = Response(status=304)
            # if client_etag matches cache_etag return not modified
        elif etag and cached_etag and etag==quote_etag(cached_etag):
            response = Response(status=304)
            # if etag is in cache, but client's etag is stale or empty,
            # serve back data from cache and refresh etag.
        elif cached_data:
            response = json_response(cached_data, status=200, json_dumps=False)

        if response:
            if cached_etag:
                response.set_etag(cached_etag)
            if cached_timestamp:
                response.last_modified = cached_timestamp
            return response

    def cache_response(self, response, path, params=None, role=None):
        if params is None:
            params = {}
        key = self.get_resource_key(path, params=params, role=role)
        data = response.data
        response.add_etag()
        etag, is_weak = response.get_etag()
        response_cache = dict(
            data=data,
            path=path,
            role=json.dumps(role), # serializing b/c redis doesn't recognize None
            etag=etag,
            timestamp=time.mktime(response.last_modified.timetuple()),
            params=json.dumps(ordered_params(params)),
        )
        self.store.set_resource(key, response_cache)
        #self.store.set_resource_field(key, 'data', data)
        #self.store.set_resource_field(key, 'meta', json.dumps(meta))
        return True

    def get_timestamp(self):
        dt = datetime.datetime.utcnow()
        return time.mktime(dt.timetuple())


class RedisCacheStore(object):

    def __init__(self, prefix=None, host=None, port=None, db=None):
        if prefix is None:
            prefix = bootstrapper.app.config['PROJECT_NAME']
        self.prefix = prefix
        #self.template = "{prefix}::%s".format(prefix=self.prefix)
        #self.template = "{prefix}:{{key}}:{{field}}".format(prefix=self.prefix)
        self.template = "{prefix}:{{key}}".format(prefix=self.prefix)

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
        keys = self.get_keys_from_pattern(pattern)
        rv = dict((k, self.server.hgetall(k)) for k in keys)
        return rv

    def get_keys_from_pattern(self, pattern):
        """
        We fetch all keys that match the pattern.
        """
        rv = set()
        cursor = 0
        count = 1000
        match = self.template.format(key=pattern)
        while True:
            cursor, keys = self.server.scan(cursor, count=10000, match=match)
            rv = rv.union(keys)
            # if full iteration, end the loop
            if cursor==0:
                break
        return rv

    def set_resource(self, key, data):
        hkey = self.template.format(key=key)
        return self.server.hmset(hkey, data)

    def delete_from_pattern(self, pattern):
        keys = self.get_keys_from_pattern(pattern=pattern)
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


def cache_wrapper(fnc, cache):
    # /!\ simplified cache wrapper, specific to the problem domain of the 
    # CCA. A more generalized solution will have to be designed for use in
    # other projects.
    """
        - if user in admin level group: 
            cache key must include admin as role
        - else:
            cache key ignores role

        TODO: a finer grained management of roles in the caching.
            - possibly users might need to specify which representation they
            want as part of the request, and a check for the appropriate role 
            will be performed in their list of roles. e.g. user wants to see
            accountant representation of a resource, a check should be done to
            see if he belongs to accountant group.
            - there might also need to be a 'public' role for when users are
            not authenticated.
        
    """
    @functools.wraps(fnc)
    def wrapper(*a, **kw):
        #try:
        #    role = 'admin' if g.current_user.authorize(roles=['admin', 'dev'])\
        #                   else None
        #except:
        #    pass

        #if app.config.get('DEV_MODE', False):
        #    role = 'admin'

        # only GET and HEAD requests are cached

        path = request.path
        #params = request.args
        role = kw.get('role')
        params = kw.get('params')


        if request.method in ['GET', 'HEAD']:
            try:
                etag = request.if_none_match.to_header()
                timestamp = request.if_modified_since
                response = cache.get(path=path, params=params, role=role, 
                                     etag=etag, timestamp=timestamp)
            except CacheError:
                response = None
        else:
            raise CacheError("Uncacheable method: '{}'".format(
                method=request.method))

        if response is None:
            response = fnc(*a, **kw)
            data = response.data
            etag, is_weak = response.get_etag()
            #timestamp = formatdate(usegmt=True)
            response.last_modified = datetime.datetime.utcnow()
            cache.cache_response(response, path=path, params=params, role=role)

        return response
    return wrapper


def json_response_wrapper(fnc):
    @functools.wraps(fnc)
    def wrapper(*a, **kw):
        data = fnc(*a, **kw)
        try:
            if type(data) is tuple: 
                data, status, headers = data 
            else:
                status = headers = None
        except ValueError:
            status = headers = None
        
        response = json_response(data=data, status=status, headers=headers)

        # set response's etag
        etag = make_hash(data)
        response.set_etag(etag)
        return response
    return wrapper

def json_response(data, status=None, headers=None, json_dumps=True):
    if json_dumps:
        data = json.dumps(data, use_decimal=True)
    return Response(
        data, mimetype='application/json',
        status=status, headers=headers)

def ordered_params(o):
    # ordering sets, lists, tuples
    if isinstance(o, (list, tuple, set)):
        rv = sorted(ordered_params(e) for e in o)
        return rv
    # returning data types other than dicts
    if not isinstance(o, dict):
        return o
    # ordering multidicts
    t = type(o)
    try:
        ordered_dict = t((k, i) for k,v in o.iterlists() 
                                for i in ordered_params(v))
    except AttributeError:
        ordered_dict = t((k, i) for k,v in o.iteritems() 
                                for i in ordered_params(v))
    rv = t((k,ordered_dict.getlist(k)) for k in sorted(ordered_dict))
    return rv

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


@bootstrapper.celery.task
def load_resource_from_endpoint(endpoint, attr=None, params=None, 
                                role=None):
    if attr is None:
        attr = {}

    if params is None:
        params = {}

    path = url_for("%s.%s" % (bp.name, endpoint), **attr)
    # get response from cache
    response = cache.get(path, params=params, role=role)
    if not response:
        attr.update({'params':params, 'role':role})
        try:
            data = api_call(endpoint, **attr)
            response = json_response(data, status=200)
            response.last_modified = datetime.datetime.utcnow()
            if api_actions[endpoint]['cacheable']:
                cache.cache_response(response, path, params=params, role=role)
        except:
            return
    return json.loads(response.data)

@bootstrapper.celery.task
def load_resource_from_path(path, role=None, params=None):
    import time
    s = time.time()
    response = cache.get(path, params=params, role=role)
    logger = logging.getLogger('ccaapi')
    logger.info(time.time() - s)

    if not response:
        url_map = app.url_map
        adapter = url_map.bind('localhost')
        endpoint, attr = adapter.match(path)
        blueprint_name, blueprint_endpoint = endpoint.rsplit('.', 1)
        attr.update({'params':params, 'role':role})
        try:
            data = api_call(blueprint_endpoint, **attr)
            response = json_response(data, status=200)
            response.last_modified = datetime.datetime.utcnow()
            if api_actions[blueprint_endpoint]['cacheable']:
                cache.cache_response(response, path, params=params, role=role)
        except:
            return
    return json.loads(response.data)

@bootstrapper.celery.task
def delete_resource(endpoint, attr=None):
    if attr is None:
        attr = {}
    path = url_for("%s.%s" % (bp.name, endpoint), **attr)
    resources = cache.get_all_resources_from_path(path)
    for key, resource in resources.iteritems():
        # delete resource from cache
        cache.delete_resource_from_key(key)
    return resources

@bootstrapper.celery.task
def reload_resource(endpoint, attr=None):
    if attr is None:
        attr = {}

    # delete resource from cache
    resources = delete_resource(endpoint, attr=attr)
    # reload all previously cached resources
    for key, resource in resources.iteritems():
        # reload from api
        load_resource_from_path(
            resource['path'], role=resource.get('role'), 
            params=resource.get('params'))
