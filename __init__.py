# coding=utf8
import falcon
from collections import namedtuple
from functools import partial
import base64

from .local import release_local
from .globals import local, request
from .database import SQLAlchemy
from ._compat import iteritems, isiterable, isnumber
from .wrapper import HttpWrapper, VersionMapper
from .routing import Router

"""
used to push some objects to the thread local
"""

class BaseMiddleware(object):
    def get_action(self, request, resource, params):
        version_mapper = getattr(
            resource, 'on_{}'.format(request.method.lower()))
        return version_mapper.get_action(request, params)

class AuthMiddleware(BaseMiddleware):

    def __init__(self, app, login_function):
        self.app = app
        self.login_function = login_function

    # def process_request(self): pass

    def process_resource(self, *args, **kwargs):
        self.authentication(*args, **kwargs)
        self.authorization(*args, **kwargs)

    # def process_response(self): pass
    def authentication(self, request, response, resource, params):
        action = self.get_action(request, resource, params)
        if not (getattr(action, 'requires_auth', False) or 
                getattr(action, 'authorization', None)):
            return

        if not request.auth:
            raise falcon.HTTPUnauthorized(
                'Unauthorized',
                'Missing Authentication header',)
        if isinstance(request.auth, unicode):
            auth = request.auth.encode('utf8')
        try:
            auth_type, user_and_key = request.auth.split(' ', 1)
        except ValueError:
            raise falcon.HTTPBadRequest(
                'Bad Request',
                'Authentication header improperly formed',)

        tenant = request.context.get('tenant', None)
        tenant_id = tenant.tenant_id if tenant else None
        user, key = base64.b64decode(user_and_key).decode('utf8').split(':', 1)
        user = self.login_function(user, key, tenant_id)
        if not user:
            raise falcon.HTTPUnauthorized(
                    'Unauthorized',
                    'Wrong username or password.',)
        request.context['user'] = user

    def authorization(self, request, response, resource, params):
        action = self.get_action(request, resource, params)
        authorization = getattr(action, 'authorization', None)
        
        if not authorization:
            return

        user = request.context.get('user', None)
        if user:
            request.context['authorized'] = auth = user.authorize(
                    authorization, params)

        if not (user and auth):
            raise falcon.HTTPForbidden('Forbidden', 'Unauthorized user.')


class GlobalsMiddleWare(BaseMiddleware):

    def __init__(self, application):
        self.application = application

    def process_request(self, request, response):
        local.request = request

    #def process_resource(self, request, response, resource, params):
    #    pass

    def process_response(self, request, response, resource, req_succeeded):
        """committing db session if config says so""" 
        if self.application.db.config['commit_on_response']:
            self.application.db.session.commit()

        """ removing db session from the registry """
        self.application.db.Session.remove()

        release_local(local)


class TenantMiddleware(BaseMiddleware):
    def __init__(self, application, get_tenant_func):
        self.application = application
        self.get_tenant = get_tenant_func

    def process_resource(self, request, response, resource, params):
        action = self.get_action(request, resource, params)
        if not (getattr(action, 'multitenant', False) 
                or getattr(action, 'tenants', None)):
            return

        tenant_name = params.get('tenant', None)
        if action.tenants and tenant_name not in action.tenants:
            tenant_name = None

        request.context['tenant'] = tenant = self.get_tenant(tenant_name)

        if not tenant:
            raise falcon.HTTPNotFound(
                title='Not Found', description='Resource does not exist.')

class API(object):
        
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

    def add_route(self, url, action_func, methods=None, version=None,
                  *args, **kwargs):
        kwargs.setdefault('multitenant', self.default_multitenancy)
        action = HttpWrapper(self, action_func, **kwargs)
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

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)
