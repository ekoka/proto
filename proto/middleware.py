# coding=utf8
import base64

import falcon

from .globals import local
from .local import release_local

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
        if '-' in user:
            user, role = user.split('-', 1)
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

        # if the user is pushing for a role
        if request.params.get('__role'):
            request.context.priority_role = request.params['__role']


"""
used to push some objects to the thread local
"""
class GlobalsMiddleWare(BaseMiddleware):

    def __init__(self, application):
        self.application = application

    def process_request(self, request, response):
        local.request = request
        local.context = request.context

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

