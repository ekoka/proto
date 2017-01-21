import unittest
import json
from datetime import datetime, date, time
from decimal import Decimal

from .formatters import JSONFormatter

class JsonFormatterTest(unittest.TestCase):
    def test_handles_primitives(self):
        d = {
            "k1": "abc",
            "k2": {
                "k1": "abc",
                "k3": 3,
                "k4": '3',
            },
            "k3": ['a', 'b', 'c'],
            "k4": 3,
            "k5": '3',
        }

        result = json.dumps(d, cls=JSONFormatter)
        d2 = json.loads(result)

        for k,v in d.iteritems(): 
            self.assertEqual(d2[k], v)

    def test_handles_tuples_and_sets(self):
        d = {
            "k1": {
                "tuple": ('a', 'b', 'c'),
                "set": {'a', 'b', 'c'},
            }
        }

        result = json.dumps(d, cls=JSONFormatter)
        d2 = json.loads(result)

        self.assertTrue(isinstance(d2['k1']['tuple'], list))
        self.assertEqual(d['k1']['tuple'], tuple(d2['k1']['tuple']))
        self.assertEqual(d['k1']['set'], set(d2['k1']['set']))

    def test_handles_dates_and_times(self):

        d = {
            "k1": datetime.now(),
            "k2": datetime.now().date(),
            "k3": datetime.now().time(),
        }
        result = json.dumps(d, cls=JSONFormatter)
        d2 = json.loads(result)

        for k,v in d.iteritems(): 
            self.assertEqual(d2[k], v.isoformat())
        

    def test_handles_decimals(self):
        d = {
            "k1": Decimal(0.3343),
            "k2": Decimal(9.42),
        }
        result = json.dumps(d, cls=JSONFormatter)
        d2 = json.loads(result)

        for k, v in d.iteritems():
            self.assertEqual(d2[k], float(v))
