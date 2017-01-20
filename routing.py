import falcon
from falcon.routing import create_http_method_map, compile_uri_template
import re

from ._compat import isiterable, isnumber


class Route(object):

    def __init__(self, url, action_func=None, methods=None, version=None, 
                 converters=None):
        self.url = url
        if action_func:
            self.add_action(action_func, methods=methods, version=version, 
                            converters=converters)

    @property
    def actions(self):
        return self.__dict__.setdefault('_actions', {})

    def add_action(self, action_func, methods=None, version=None, 
                   converters=None):

        if methods is None:
            methods = ['GET']

        if not isiterable(methods):
            raise Exception('non-iterable HTTP methods.')

        if set(methods).difference(falcon.HTTP_METHODS):
            method = list(set(methods).difference(falcon.HTTP_METHODS))[0]
            raise Exception("Unsupported HTTP method: '{0}'.".format(method))

        if version is not None and not isnumber(version, exclude_decimal=True):
            raise Exception('Version specified at routing must be an integer.')

        for method in methods:
            self.actions.setdefault(method, {})[version] = action = dict(
                action_func=action_func,
                converters=converters,
                func_name=action_func.func_specs.name 
                        if hasattr(action_func, 'func_specs') else
                        action_func.__name__)

    def get_action(self, method=None, version=None):
        if method is None:
            method = 'GET'

        try:
            return self.actions[method][version]
        except KeyError:
            pass


class Router(object):
    _converter_pattern = r"{(?P<var>[^}]+?):(?P<converter>.+?)}"
    
    @property
    def routes(self):
        return self.__dict__.setdefault('_routes', {})

    @property
    def reverse_routes(self):
        return self.__dict__.setdefault('_reverse_routes', {})

    def _get_converters(self, url):
        converter_pattern = re.compile(self._converter_pattern)
        rv = {}

        for match in converter_pattern.finditer(url):
            converter = match.group('converter')
            var = match.group('var')
            try:
                rv[var] = eval(converter)
            except NameError:
                __import__(converter)
                rv[var] = eval(converter)

        return rv

    def _falcon_url_template(self, url):
        converter_pattern = re.compile(self._converter_pattern)
        replace_pattern = "{\g<var>}"

        return converter_pattern.sub(replace_pattern, url)

    def add_route(self, url, action_func, methods=None, version=None):

        converters = self._get_converters(url)
        url = self._falcon_url_template(url)

        route = self.routes.setdefault(url, Route(url))
        route.add_action(action_func, methods=methods, version=version,
                         converters=converters)

        for method in methods:
            func_name = route.actions[method][version]['func_name']
            url_map = self.reverse_routes.setdefault(func_name, {})
            # a single action/method combo can be be linked to by multiple urls
            url_map.setdefault(method, []).append(url)

        
    # a reverse mapper to ease implementation of HATEOAS
    def action_to_url(self, func, method='GET', version=None, hint=None, 
                      *args, **kwargs):
        if hasattr(func, 'func_specs'):
            func_name = func.func_specs.name
        elif hasattr(func, '__name__'):
            func_name = func.__name__
        else:
            func_name = func

        urls = self.reverse_routes[func_name][method][version]
        
        def _find_hint(urls, hint):
            for url in urls:
                if hint in url:
                    return url 
            raise Exception("Could not find hint '{0}' among registered urls."
                            .format(hint))

        if hint:
            url = _find_hint(urls, hint)
        else:
            url = urls[0] 
        
        if version:
            return self.url_base + '/v{0}'.format(version) + url
        else:
            return self.url_base + url 

