# coding=utf8
from collections import namedtuple

import falcon

from ._compat import iteritems
from .wrapper import Wrapper, VersionMapper
from .routing import Router

class Application(object):
        
    def __init__(self, config, default_multitenancy=False):
        self.config = self._load_config(config)
        self.url_base = self.config.get('URL_BASE', '')
        self.default_multitenancy = default_multitenancy
        self.router = Router()
        self.middleware = []

    def _load_config(self, config):
        rv = {}
        for key in dir(config):
            if key.isupper():
                rv[key] = getattr(config, key)
        return rv

    def add_route(self, url, action_func, input_formatters, output_formatters,
                  methods=None, version=None, *args, **kwargs):
        kwargs.setdefault('multitenant', self.default_multitenancy)
        action = Wrapper(self, action_func, input_formatters, 
                         output_formatters, **kwargs)
        self.router.add_route(url, action, methods=methods, version=version)

    def serve(self):
        self.wsgi_app = self.api = falcon.API(middleware=self.middleware)

        for url, route  in iteritems(self.router.routes):
            resource = {}
            for method, versioned_routes in iteritems(route.actions):
                method_handler_name = 'on_{0}'.format(method.lower())
                resource[method_handler_name] = VersionMapper(versioned_routes)

            # a Resource class that falcon can talk to in the form of a 
            # namedtuple.
            Resource = namedtuple('Resource', resource.keys())
            resource = Resource(**resource)

            url = self.url_base + route.url
            versioned_url = self.url_base + '/v{version}' + route.url

            self.api.add_route(url, resource)
            self.api.add_route(versioned_url, resource)

        return self.wsgi_app

    def action_to_url(self, action, method='GET', version=None, hint=None, 
                      **params):
        template = self.router.action_to_url(
            action, method=method, version=version, hint=hint, **params)
        if version:
            rv = self.url_base + '/v{0}'.format(version) + template
        else:
            rv = self.url_base + template 
        return rv.format(**params)

    @property
    def cache(self):
        try:
            return self._cache
        except:
            raise

    @cache.setter
    def cache(self, cache):
        self._cache = cache


    def populate_from_cache(self, request, response, role=None):
        key_parts = dict(
            path=request.path, params=request.params, role=role)
        cached_resource = self.cache.load_response(**key_parts)
        if not cached_resource:
            # skip
            return False

        cached_data = cached_resource.get('data')
        etag = request.if_none_match
        timestamp = request.if_modified_since

        # if client_etag matches cache_etag return not modified
        if etag:
            cached_etag = cached_resource.get('etag')
            if cached_etag and etag==cached_etag:
                response.status = falcon.HTTP_304
        # if not deactivated and cached_etag:
        elif timestamp: 
            try:
                cached_timestamp = datetime.fromtimestamp(
                    float(cached_resource['timestamp']))
            except:
                cached_timestamp = None
            if cached_timestamp and timestamp>=cached_timestamp:
                response.status = falcon.HTTP_304

        if response.status==falcon.HTTP_304:
            return True

        # if etag is in cache, but client's etag is stale or empty,
        # serve back data from cache and refresh etag.
        response.data = cached_data
        response.status = falcon.HTTP_200
        if cached_resource.get('etag'):
            response.etag = cached_resource['etag']
        elif cached_resource.get('timestamp'):
            response.last_modified = cached_resource['timestamp']
        return True

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)
