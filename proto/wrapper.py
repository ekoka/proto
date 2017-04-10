import inspect
from datetime import datetime

from ._compat import iteritems

class FuncSpec(object):
    def __init__(self, func):
        self.name = func.__name__
        self.module = func.__module__
        info = inspect.getargspec(func)
        self.defaults = info.defaults
        self.allargs = info.args
        self.args = info.args[:-len(info.defaults)] if info.defaults else []
        self.kwargs = info.args[-len(info.defaults):] if info.defaults else []
        self.kwargsdict = (dict(zip(info.args[-len(info.defaults):], 
                                info.defaults)) 
                            if info.defaults else {})
        self.varargs = info.varargs
        self.varkwargs = info.keywords


class VersionMapper(object):

    def __init__(self, api_versioned_routes):
        self.api_versioned_routes = api_versioned_routes

    def get_route(self, request, url_version=None):
        version = set([url_version]) if url_version else set()
        # TODO get version from query string params
        # TODO get version from request header
        if len(version) > 1:
            # TODO make this an HTTP error
            raise Exception('Conflicting versions requested.')
        try:
            version = list(version)[0]
        except IndexError:
            version = None
        # if a version is not specified it either means that
        # - we want the version which did not specify a number
        # - or we want the latest version
        return self.api_versioned_routes.get(version, None)

    def get_action(self, request, params=None):
        url_version = (params.get('version', None) if params else
                       None)
        route = self.get_route(request, url_version=url_version)
        return route['action_func']

    def __call__(self, request, response, **params):
        route = self.get_route(
            request, url_version=params.pop('version', None))

        if route is None:
            #TODO: add a not found handler here 
            pass

        # converting param values to types specified during routing
        if route.get('converters', None):
            for name, converter in iteritems(route['converters']):
                try:
                    params[name] = converter(params[name])
                except KeyError:
                    pass

        #response.body = route['action_func'](request, response, **params)
        route['action_func'](request, response, **params)
        return response

"""
- positional arguments should come from the url
- keyword arguments should come from parameters
- xargs arguments?
- xkwargs arguments?
"""

class Wrapper(object):

    def __init__(self, app, func, input_formatters, output_formatters, 
                 **kwargs):

        self.app = app
        self.func = func
        self.func_specs = FuncSpec(func)
        self.input_formatters = input_formatters
        self.output_formatters = output_formatters

        kwargs_defaults = dict(version=None,
            requires_auth=False, authorization=None, 
            #expects_data=False, expects_params=False, expects_file=False, 
            #expects_user=False, expects_role=False, 
            cacheable=False, endpoint=None, #if_match=False, if_none_match=False,
            multitenant=False, tenants=[],
        )

        for k,d in iteritems(kwargs_defaults):
            setattr(self, k, kwargs.get(k, d))

        self.requires_auth = (True 
            if ('__user__' in self.func_specs.allargs) or self.authorization
            else  False)

    def __call__(self, request, response, **kwargs):
        api_version = kwargs.pop('version', None)
        tenant = kwargs.pop('tenant', None)

        if self.requires_auth and not request.context.get('user', None):
            #TODO: make it an HTTP error
            raise Exception('User must be logged in.')

        if self.authorization and not request.context.get('authorized', False):
            #TODO: make it an HTTP error
            raise Exception('Unauthorized user.')

        params = dict()
        for arg, value in iteritems(kwargs):
            params[arg] = value

        for param, value in iteritems(request.params):
            if param in self.func_specs.kwargsdict:
                # not overwriting params
                params.setdefault(param, value)

        cached = False
        if self.cacheable:
            # TODO: if the resource expects a role, fetch it from the user and
            # add it to the call here. 
            # The present wrapper should have an attribute to remember the 
            # qualifying roles during routing. They should then be compared 
            # to the user's currently assumed role (user.current_role) to
            # determine which representation of the resource should be
            # returned by either the cache or the api call.
            cached = self.app.populate_from_cache(request, response)

        if cached:
            return response

        # TODO
        # other potential objects of interest
        # - data
        # - files

        if '__app__' in self.func_specs.allargs:
            params['__app__'] = self.app

        if '__request__' in self.func_specs.allargs:
            params['__request__'] = request

        if '__response__' in self.func_specs.allargs:
            params['__response__'] = response

        if '__data__' in self.func_specs.allargs:
            api_data = request.bounded_stream.read()
            params['__data__'] = self.input_format(api_data)
            
        if '__user__' in self.func_specs.allargs:
            params['__user__'] = request.context.get('user', None)

        if '__tenant__' in self.func_specs.allargs:
            params['__tenant__'] = request.context.get('tenant', None)

        response.context['result'] = result = self.func(**params)
        response.data = self.output_format(result)

        if self.cacheable:
            response.last_modified = datetime.utcnow()
            self.cache.store_response(request, response)

    def input_format(self, input):
        rv = input
        for f in self.input_formatters:
            rv = f(rv)
        return rv

    def output_format(self, output):
        rv = output
        for f in self.output_formatters:
            rv = f(rv)
        return rv
