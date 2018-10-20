# -*- coding: utf-8 -*-
import urllib
from urllib.parse import urlencode
from past.builtins import basestring

def url_encode(query):
    if isinstance(query, basestring):
        query = urllib.quote_plus(query)
    else:
        query = urllib.parse.urlencode(query)
    query = query.replace('+', '%20')
    return query
