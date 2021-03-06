#!/usr/bin/python
#-*- coding: UTF-8 -*-

import logging, collections, json, pickle
from urllib2 import urlopen
from urllib import urlencode
from django.utils import timezone
from django.core.cache import cache
from datetime import datetime as dt
from datetime import timedelta
from www.models import *

_yql_url = u"http://query.yahooapis.com/v1/public/yql?"
class YQL:
    def fmt(self, code, suffix=None):
        if suffix:
            return code + suffix
        if code.isdigit():
            if int(code) >= 600000:
                return code + ".SS"
            else:
                return code + ".SZ"
        return code

    def run(self, yql):
        logging.error("YQL: %s" % yql)
        params = {
                "q": yql,
                "format": "json",
                "diagnostics": "false",
                "env": "http://datatables.org/alltables.env",
                "callback": ""
                }
        url = _yql_url + urlencode(params)
        html = urlopen(url).read()
        j = json.loads(html)
        return j['query']['results']

    def stock(self, s):
        c_key = "oquote."+s
        today = dt.now().date()
        try:
            c = pickle.loads(SimpleCache.objects.get(key=c_key).val)
            if c['date'] >= today: return c['data']
        except: pass

        code = self.fmt(s)
        yql = u'SELECT * FROM yahoo.finance.oquote WHERE symbol="%s"' % code
        results = self.run(yql)
        if not results: return Decimal(0)
        data = Decimal(results['option']['price'])

        # set to cache
        c_val = {'date': today, 'data': data}
        SimpleCache(key=c_key, val=pickle.dumps(c_val)).save()
        return data

    def stocks(self, stocks):
        data = {}
        for s in stocks:
            data[s] = self.stock(s)
        return data

    def abc(self, stocks):
        # check cache
        c_key = "_".join(stocks)
        today = dt.now().date()
        try:
            c = pickle.loads(SimpleCache.objects.get(key=c_key).val)
            if c['date'] >= today: return c['data']
        except: pass

        codes = [ '"'+self.fmt(c) +'"' for c in stocks ]
        yql = u'select * from yahoo.finance.quote where symbol in (%s)' % ','.join(codes)
        results = self.run(yql)

        quote = results['quote']
        if isinstance(quote, dict):
            k = stocks[0]
            return {k: Decimal(quote['LastTradePriceOnly'])}

        data = dict( (obj['symbol'].split(".")[0], Decimal(obj['LastTradePriceOnly'])) for obj in quote )
        # set to cache
        c_val = {'date': today, 'data': data}
        SimpleCache(key=c_key, val=pickle.dumps(c_val)).save()
        return data

    def stock_history_(self, stock_code, start_date, end_date, suffix=None):
        code = self.fmt(stock_code, suffix)
        begin = start_date.strftime("%Y-%m-%d")
        end = end_date.strftime("%Y-%m-%d")
        tpl = u'select * from yahoo.finance.historicaldata where symbol = "%s" and startDate = "%s" and endDate = "%s"'
        yql = tpl % ( code, begin, end)
        results = self.run(yql)
        if results == None:
            #if not suffix:
                #return self.stock_history_(stock_code, start_date, end_date, ".SS")
            return []

        quote = results['quote']
        if isinstance(quote, dict):
            quote = [ quote ]
        try:
            return [(dt.strptime(obj['date'], "%Y-%m-%d").date(), obj) for obj in quote]
        except:
            return [(dt.strptime(obj['Date'], "%Y-%m-%d").date(), obj) for obj in quote]


    def stock_history(self, stock_code, start_date, end_date, suffix=None):
        if stock_code == "": return []

        # check cache
        c = None
        c_key = "yql."+stock_code
        try: c = pickle.loads(SimpleCache.objects.get(key=c_key).val)
        except: pass
        if c and c['start_date'].date() <= start_date.date() and c['end_date'].date() >= end_date.date():
            logging.error("YQL: query stock [%s], hit cache" % stock_code)
            return c['data']

        # split to multi query
        data = []
        begin = start_date
        while begin.date() < end_date.date():
            end = begin + timedelta(days=400)
            out = self.stock_history_(stock_code, begin, end, suffix)
            data.extend( out )
            begin = end

        # set to cache
        c_val = {'start_date': start_date, 'end_date': end_date, 'data': data}
        SimpleCache(key=c_key, val=pickle.dumps(c_val)).save()
        logging.error("got history: %d points" % len(data))
        return data

    def stocks_history(self, stocks):
        logging.error("stocks.count = %d" % len(stocks))
        output = {}
        for code, start, end in stocks:
            output[code] = self.stock_history(code, start, end)
        return output


