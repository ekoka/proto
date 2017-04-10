import testtools

class ApplicationTest(testtools.TestCase):

    def test_fetch_cache_response(self):
        request = self.create_environ()
        response = self.create_response()
        class MockCache(object):
            def load_response(self, **key_parts):
                return dict(
                    data=rndstr(),
                    etag=rndstr(),
                    timestamp=datetime.datetime.now(),
                )
        cache = MockCache()
        wrapper.cache = cache
