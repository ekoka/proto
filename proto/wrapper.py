import inspect
from collections import namedtuple

from ._compat import iteritems
from .globals import current_user
from .formatters import json_output_formatter, json_input_formatter

class FuncSpec(object):
    def __init__(self, func):
        try:
            self.name = func.func_name
        except AttributeError:
            self.name = func.__name__
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

        if route.get('converters', None):
            for name, converter in iteritems(route['converters']):
                try:
                    params[name] = converter(params[name])
                except KeyError:
                    pass

        response.body = route['action_func'](request, response, **params)
        return response

"""
- positional arguments should come from the url
- keyword arguments should come from parameters
- xargs arguments?
- xkwargs arguments?
"""
class HttpWrapper(object):

    # TODO: maybe pass this as a param
    output_formatters = {'json': [json_output_formatter]}
    input_formatters = {'json': [json_input_formatter]}

    def __init__(self, api, func, **kwargs):

        self.api = api
        self.func = func
        self.func_specs = FuncSpec(func)

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
                              if 'api_user' in self.func_specs.allargs else
                              False)

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


        # TODO
        # other potential objects of interest
        # - data
        # - files

        if '__api__' in self.func_specs.allargs:
            params['__api__'] = self.api

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

        return self.output_format(self.func(**params))

    def input_format(self, input, content_type='json'):
        rv = input
        for f in self.input_formatters.get(content_type, []):
            rv = f(rv)
        return rv

    def output_format(self, output, content_type='json'):
        rv = output
        for f in self.output_formatters.get(content_type, []):
            rv = f(rv)
        return rv
