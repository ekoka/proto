# coding=utf8
from uuid import uuid4

from falcon.testing import rand_string

def rndstr(min=5, max=10):
    return rand_string(min, max)

