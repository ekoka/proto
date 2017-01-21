from datetime import datetime, date, time
from decimal import Decimal
from functools import partial

import json

from ._compat import isiterable, isnumber

class JSONFormatter(json.JSONEncoder):

    """ currently handles 
    - numbers: to str
    - iterables: to list
    - bytes: to unicode or base64
    - dates and datetimes: to isoformat
    """

    @property
    def formatters(self):
        rv = self.__dict__.setdefault('_formatters', {})
        return rv

    def add_formatter(self, format_type, formatter):
        self.formatters[format_type] = formatter

    def default(self, o):
        for format_type, formatter in self.formatters:
            if isinstance(o, format_type):
                return formatter(o)

        if isinstance(o, (date, datetime, time)):
            return o.isoformat()

        elif isinstance(o, bytes):
            try:
                return o.decode('utf8')
            except UnicodeDecodeError:
                return base64.b64encode(o)

        elif isinstance(o, Decimal):
            return float(o)

        elif isiterable(o):
            return list(o)

        elif isnumber(o):
            return str(o)

        raise TypeError("Type not serializable")

json_output_formatter = partial(json.dumps, cls=JSONFormatter)
json_input_formatter = partial(json.loads)
