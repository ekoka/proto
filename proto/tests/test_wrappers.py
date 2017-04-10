import testtools

from falcon import testing as falcon_testing, Response

from proto.wrapper import (FuncSpec, VersionMapper, Wrapper)

from . import rndstr

class FuncSpecTest(testtools.TestCase):
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

class BaseTest(testtools.TestCase):
    def create_environ(self):
        return falcon_testing.create_environ(
            path='/api/test', query_string='a=3&b=2&c=1&b=4&b=5&a=3',
            protocol='HTTP/1.1', scheme='http', host='localhost', port=None,
            headers=None, app='', body='', method='GET', wsgierrors=None,
            file_wrapper=None)

    def create_response(self):
        return Response()

class VersionMapperTest(BaseTest):
    def setUp(self):
        super(VersionMapperTest, self).setUp()
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

        self.request = self.create_environ()

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
            response['params'] = params
        def fncNone(request, response, **params):
            response['params'] = params

        vm = self.version_mapper

        # mapping
        vm.api_versioned_routes = {
            1: {'action_func': fnc1}, 
            None: {'action_func': fncNone, 'converters':{'a':str, 'b':int}},
        }


        response = {}
        # same response object passed to the handler must be returned
        # by `version_mapper.__call__()`

        # test explicit `None` api version
        params = {'version': None}
        response = vm(self.request, response, **params)
        self.assertIsNone(response['params'].get('a'))

        # test int api version
        params = {'version': 1, 'a':2}
        response = vm(self.request, response, **params)
        self.assertEqual(response['params']['a'], 2)

        # test implicit `None` api version
        params = {}
        response = vm(self.request, response, **params)
        self.assertIsNone(response['params'].get('a'))

        # test params type conversion
        params = {'a':1, 'b':'2'}
        response = vm(self.request, response, **params)
        self.assertNotEqual(response['params']['a'], 1)
        self.assertEqual(response['params']['a'], '1')
        self.assertNotEqual(response['params']['b'], '2')
        self.assertEqual(response['params']['b'], 2)

class WrapperTest(BaseTest):
    def test_default_params(self):
        app = None 
        def abc(a, b, c, __user__, d=3, e=None): pass
        tenant = rndstr()

        wrapper = Wrapper(app, abc, None, None, cacheable=True, 
                          tenants=[tenant])

        # if not specified some settings should be set to a default
        # value on the wrapper
        self.assertFalse(wrapper.multitenant)
        self.assertIsNone(wrapper.authorization)
        self.assertIsNone(wrapper.endpoint)

        # specified settings should override defaults
        self.assertTrue(wrapper.cacheable)
        self.assertIn(tenant, wrapper.tenants)

        # when `__user__` param present on func signature auth must be required
        self.assertTrue(wrapper.requires_auth)

        # when authorization specified on func signature auth must be required
        def abc(a, b, c, d=3, e=None): pass
        wrapper = Wrapper(app, abc, None, None, authorization=['admin'])
        self.assertTrue(wrapper.requires_auth)

        # when neither authorization nor __user__ specified on func signature
        # auth is not required
        wrapper = Wrapper(app, abc, None, None)
        self.assertFalse(wrapper.requires_auth)

    def test_call(self):
        app = None 
        def abc(a, b, c, __user__, d=3, e=None): pass
        wrapper = Wrapper(app, abc, None, None)
        self.fail()
        # wrapper(request, response, version=None, tenant=None)


    #def __call__(self, request, response, **kwargs):
    #    api_version = kwargs.pop('version', None)
    #    tenant = kwargs.pop('tenant', None)
    #    if self.requires_auth and not request.context.get('user', None):
    #        #TODO: make it an HTTP error
    #        raise Exception('User must be logged in.')

    #    if self.authorization and not request.context.get('authorized', False):
    #        #TODO: make it an HTTP error
    #        raise Exception('Unauthorized user.')

    #    params = dict()
    #    for arg, value in iteritems(kwargs):
    #        params[arg] = value

    #    for param, value in iteritems(request.params):
    #        if param in self.func_specs.kwargsdict:
    #            # not overwriting params
    #            params.setdefault(param, value)

    #    cache_found = False
    #    if self.cacheable:
    #        # TODO: if the resource expects a role, fetch it from the user and
    #        # add it to the call here. 
    #        # The present wrapper should have an attribute to remember the 
    #        # qualifying roles during routing. They should then be compared 
    #        # to the user's currently assumed role (user.current_role) to
    #        # determine which representation of the resource should be
    #        # returned by either the cache or the api call.
    #        cache_found = self.app.fetch_cached_response(request, response)

    #    if cache_found:
    #        return

    #    # TODO
    #    # other potential objects of interest
    #    # - data
    #    # - files

    #    if '__app__' in self.func_specs.allargs:
    #        params['__app__'] = self.app

    #    if '__request__' in self.func_specs.allargs:
    #        params['__request__'] = request

    #    if '__response__' in self.func_specs.allargs:
    #        params['__response__'] = response

    #    if '__data__' in self.func_specs.allargs:
    #        api_data = request.bounded_stream.read()
    #        params['__data__'] = self.input_format(api_data)
    #        
    #    if '__user__' in self.func_specs.allargs:
    #        params['__user__'] = request.context.get('user', None)

    #    if '__tenant__' in self.func_specs.allargs:
    #        params['__tenant__'] = request.context.get('tenant', None)

    #    response.context['result'] = result = self.func(**params)
    #    response.data = self.output_format(result)

    #    if self.cacheable:
    #        response.last_modified = datetime.utcnow()
    #        self.cache.store_response(request, response)


