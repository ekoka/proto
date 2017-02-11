import unittest

from falcon import testing as falcon_testing

from proto.wrapper import (
    FuncSpec,
    VersionMapper,
    HttpWrapper,
)

from . import rndstr

class FuncSpecTest(unittest.TestCase):
    def test_reflection(self):
        mock_fnc = lambda a,b,c, d="alpha", e=None, *arg, **kwargs: None
        fnc_spec = FuncSpec(mock_fnc)
        self.assertEqual(fnc_spec.name, mock_fnc.__name__)
        self.assertEqual(len(fnc_spec.defaults), 2)
        self.assertEqual(fnc_spec.defaults[0], "alpha")
        self.assertEqual(fnc_spec.defaults[1], None)
        self.assertEqual(fnc_spec.kwargsdict['d'], 'alpha')
        self.assertEqual(fnc_spec.kwargs[0], 'd')
        self.assertEqual(len(fnc_spec.args), 3)
        self.assertEqual(len(fnc_spec.kwargs), 2)
        self.assertEqual(len(fnc_spec.allargs), 5)
        self.assertEqual(fnc_spec.varargs, 'arg')
        self.assertEqual(fnc_spec.varkwargs, 'kwargs')

class VersionMapperTest(unittest.TestCase):

    def setUp(self):
        def abc(): pass
        def cba(): pass
        def xyz(): pass

        versioned_routes = {
                1: {'name': 'route_1', 'action_func': abc},
                2: {'name': 'route_2', 'action_func': cba},
                None: {'name': 'route_None', 'action_func': xyz},
        }

        self.version_mapper = VersionMapper(
            api_versioned_routes=versioned_routes)

        self.request = falcon_testing.create_environ(
            path='/api/test', query_string='a=3&b=2&c=1&b=4&b=5&a=3',
            protocol='HTTP/1.1', scheme='http', host='localhost', port=None,
            headers=None, app='', body='', method='GET', wsgierrors=None,
            file_wrapper=None)

    def test_get_route(self):
        route = self.version_mapper.get_route(self.request, url_version=None)
        self.assertEqual(route['name'], 'route_None')
        route = self.version_mapper.get_route(self.request, url_version=2)
        self.assertEqual(route['name'], 'route_2')
        # TODO get version from query string params
        # TODO get version from request header

    def test_get_action(self):
        params = {'version': 1}
        action_func = self.version_mapper.get_action(
            self.request, params=params)
        self.assertEqual(action_func.__name__, 'abc')

    def test_call(self):
        # handlers
        def fnc1(request, response, **params):
            response['called'] = 1
        def fncNone(request, response, **params):
            response['called'] = None

        vm = self.version_mapper

        # mapping
        vm.api_versioned_routes = {
            1: {'action_func': fnc1}, 
            None: {'action_func': fncNone}
        }

        # same response object passed to the handler must be returned
        # from `version_mapper.__call__()`
        response = {}

        # test explicit `None` api version
        params = {'version': None}
        response = vm(self.request, response, **params)
        self.assertIsNone(response['called'])

        # test int api version
        params = {'version': 1}
        response = vm(self.request, response, **params)
        self.assertEqual(response['called'], 1)

        # test implicit `None` api version
        params = {}
        response = vm(self.request, response, **params)
        self.assertIsNone(response['called'])



    #def __call__(self, request, response, **params):
    #    route = self.get_route(
    #        request, url_version=params.pop('version', None))

    #    if route is None:
    #        #TODO: add a not found handler here 
    #        pass

    #    # converting param values to types specified during routing
    #    if route.get('converters', None):
    #        for name, converter in iteritems(route['converters']):
    #            try:
    #                params[name] = converter(params[name])
    #            except KeyError:
    #                pass

    #    #response.body = route['action_func'](request, response, **params)
    #    route['action_func'](request, response, **params)
    #    return response


class HttpWrapperTest(unittest.TestCase):
    pass

