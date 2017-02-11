# coding=utf8
from uuid import uuid4

def rndstr():
    return uuid4().hex[:6]

