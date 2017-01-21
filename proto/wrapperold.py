import inspect
import json
from collections import namedtuple

from mudplay._compat import iteritems
from mudplay.globals import current_user

class FuncSpec(object):
    def __init__(self, func):
        info = inspect.getargspec(func)
        self.defaults = info.defaults
        self.allargs = info.args
        self.args = info.args[:-len(info.defaults)]
        self.kwargs = info.args[-len(info.defaults):]
        self.kwargsdict = dict(zip(info.args[-len(info.defaults):], 
                                   info.defaults))
        self.varargs = info.varargs
        self.varkwargs = info.keywords


"""
- positional arguments should come from the url
- keyword arguments should come from parameters
- xargs arguments?
- xkwargs arguments?
"""
class HttpWrapper(object):

    def __init__(self, api, url, methods, **kwargs):

        for k,d in iteritems(kwargs_defaults):
            setattr(self, k, kwargs.get(k, d))

        route = {}

        for method, versioned_actions in iteritems(methods):
            method_handler_name = 'on_{0}'.format(method.lower())
            route[method_handler_name] = partial(
                self.action_mapper, versioned_actions=versioned_actions)

        # a tailored made Resource class that falcon can talk to 
        # in the form of a namedtuple.
        Resource = namedtuple('Resource', route.keys())

        self.route = Resource(**route)

        url = self.url_base + url
        versioned_url = self.url_base + '/v{version}' + url

        api.add_route(url, self)
        api.add_route(versioned_url, self)


    def __init__(self, api, url, methods, **kwargs):
        kwargs_defaults = dict(version=None,
            authenticate=False, authorize=None, 
            #expects_data=False, expects_params=False, expects_file=False, 
            #expects_user=False, expects_role=False, 
            cacheable=False, endpoint=None, #if_match=False, if_none_match=False,
        )

        self.func_specs = FuncSpec(func)

        for k,d in iteritems(kwargs_defaults):
            setattr(self, k, kwargs.get(k, d))

    def action_mapper(self, request, response, versioned_actions, version=None):
        version_from_url = version # this is provided by the falcon router
        version = self.determine_version(request, version_from_url)
        # if a version is not specified it either means that
        # - we want the version which did not specify a number
        # - or we want the latest version
        action = versioned_actions.get(version, None)
        if action is None:
            #TODO: add a not found handler here 
            pass

        response.body = json.dumps(action(*self.args, **self.kwargs))
        return response

    def determine_version(self, request, version_from_url=None):
        version = set([version_from_url]) if version_from_url else set()
        # TODO get version from query string params
        # TODO get version from request header
        if len(version) > 1:
            raise Exception('Conflicting versions requested.')
        try:
            return list(version)[0]
        except IndexError:
            pass

    def __call__(self, request, response, **kwargs):
        api_version = kwargs.pop('version', None)

        # if user must be logged in
        if self.authenticate and not self.api.get_current_user():
            raise Exception('User must be logged in.')

        # TODO: put in a method
        if self.authorize:
            try:
                u = app.get_current_user()
                authorized = u.authorize(self.authorize, kwargs)
            except AttributeError:
                # did not find current_user
                pass
            if not authorized:
                # TODO: Forbidden
                raise Exception('Forbidden')


        params = dict()
        for arg, value in iteritems(kwargs):
            params[arg] = value

        for param, value in iteritems(request.params):
            if param in self.func_specs.kwargsdict:
                params.setdefault(param, value)

        # other potential objects of interest
        # - authenticated user
        # - data
        # - files
        # - request
        # - response
        #if 'http_request' in self.func_specs.args:
        #    params['http_request'] = request
        #if 'http_response' in self.func_specs.args:
        #    params['http_response'] = response

        if 'http_request' in self.func_specs.allargs:
            params['http_request'] = request

        if 'http_response' in self.func_specs.allargs:
            params['http_response'] = response

        if 'api_data' in self. func_specs.allargs:
            params['api_data'] = request.context.data
            
        if 'api_user' in self. func_specs.allargs:
            params['api_user'] = request.context.user
            

        #if self.expects_user:
        #    params[self.expects_user] = request.context.user
        #    if not params[self.expects_user]:
        #        # TODO: raise http error
        #        raise Exception('Resource requires authorized user')

        return self.format(self.func(**params))

    def format(self, output):
        for f in self.formatters:
            output = f(output)
        return output


def authorization(fnc, roles):
    @functools.wraps(fnc)
    def wrapper(*a, **kw):
        authorized = app.config.get('DEV_MODE', False)
        try:
            u = g.current_user
            authorized = u.authorize(roles, kw) or authorized
        except AttributeError:
            # did not find current_user in g
            pass
        if authorized:
            return fnc(*a, **kw)
        raise werk_exc.Forbidden()
    return wrapper
