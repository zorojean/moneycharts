#!/usr/bin/python
#-*- coding: UTF-8 -*-

import logging, re, time, bisect
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from decimal import Decimal
from datetime import datetime, timedelta
from www.models import *
from www.codelist import Codes
from www.yql import YQL


def index(request):
    if not request.user.is_authenticated():
        return render(request, 'www/html/index.html', {'pid': 'index'})
    yql = YQL()
    a = yql.stock_history("300250", datetime(2013, 10, 1), datetime(2013, 11,30))
    return render(request, 'www/html/profile.html', {'pid': 'index'})


@login_required
def stock_list(request):
    def Name(code):
        return Codes.get(code.strip(), code)
    stocks = eval(request.user.profile.stocks_raw)
    current = [ (Name(code), s) for code,s in stocks.items() if s['num'] > 0 or code == '' ]
    history = [ (Name(code), s) for code,s in stocks.items() if s['num'] == 0 and code != '' ]
    history.sort( lambda x,y: cmp(y[1]['money'], x[1]['money']) )
    return render(request, 'www/html/stock_list.html', {'pid': 'stock_list', 'current': current, 'history': history})

def get_stock_worth(stocks):
    yql = YQL()
    active = dict( (c,s) for c,s in stocks.items() if s['num'] > 0 )
    prices = yql.stock(active.keys())
    return sum( prices[c]*s['num'] for c,s in active.items() )

@login_required
def stat(request):
    stocks = eval(request.user.profile.stocks_raw)
    request.user.profile.stocks_val = get_stock_worth(stocks)

    bills = request.user.bill_set.all()
    money = 0
    tax = 0
    fee1 = 0
    fee2 = 0
    fee3 = 0
    for b in bills:
        if b.date.year > 2012 and b.type == b.TYPES['BUY']:
            money -= b.stock_money
        tax += b.tax
        fee1 += b.fee1
        fee2 += b.fee2
        fee3 += b.fee3
    args = {
            'pid': 'stat',
            'money': money,
            'tax': tax,
            'fee1': fee1,
            'fee2': fee2,
            'fee3': fee3,
        }
    return render(request, 'www/html/stat.html', args)

def bisect_find(infos, code, day):
    '''有序查找day当天、或前一天的数据'''
    if code not in infos: return None
    hs = infos[code]
    i = bisect.bisect_left(hs, (day.date(), ))
    if i >= len(hs): i -= 1
    elif hs[i][0] != day.date(): i -= 1
    try: return hs[i][1]
    except: return None

def get_date(value):
    return datetime.strptime(value[0:8], "%Y%m%d")

def D(val):
    if val == u'---':
        return Decimal(0)
    return Decimal(val)

@login_required
def build(request):
    profile = request.user.profile
    request.user.node_set.all().delete()
    bills = request.user.bill_set.order_by('date').all()

    # get stock history data
    querys = {}
    for b in bills:
        code = b.stock_code
        if code not in querys:
            querys[code] = [code, b.date, None]
        querys[code][2] = b.date
    yql = YQL()
    infos = yql.stocks_history(querys.values())

    # build nodes
    day = bills[0].date
    today = bills[len(bills)-1].date
    oneday = timedelta(days=1)
    n = Node(type=Node.TYPES['DAY'], open=0, date=day, user=request.user)
    n.low = n.high = n.close = n.open

    stocks = {}
    base = 0
    free = 0
    nodes = []

    # FIXME there are bugs
    idx = 0
    while idx < len(bills) and day <= today:
        b = bills[idx]
        if n.date.date() == b.date.date():
            n.date = b.date
            s = stocks.get(b.stock_code, {'num': 0, 'money': 0})
            s['num'] += b.stock_num
            s['money'] += b.stock_money
            stocks[b.stock_code] = s
            free += b.stock_money
            if b.type == b.TYPES['PUT'] or b.type == b.TYPES['GET']:
                base += b.stock_money
            idx += 1
        else:
            n.low = n.high = n.close = free
            for code,s in stocks.items():
                if s['num'] == 0: continue
                # 查找当天股票价格，计算波动
                h = bisect_find(infos, code, day)
                if h:
                    n.low += s['num']*D(h['Low'])
                    n.high += s['num']*D(h['High'])
                    n.close += s['num']*D(h['Close'])
                else:
                    n.low += s['money']
                    n.high += s['money']
                    n.close += s['money']

            new_open = n.close
            n.close = n.close + n.base - base
            n.base = base
            nodes.append( n )
            day += oneday
            n = Node(type=Node.TYPES['DAY'], open=new_open, date=day, user=request.user)
            n.low = n.high = n.close = n.open
            n.base = base

    Node.objects.bulk_create( nodes )

    profile.stocks_num = len([s for s in stocks.values() if s['num'] > 0 ])
    profile.stocks_raw = repr(stocks)
    profile.stocks_val = get_stock_worth(stocks)
    profile.base = base
    profile.free = free
    profile.is_outdate = 0
    profile.save()
    return HttpResponseRedirect('/chart/k/')


@login_required
def import_bill(request):
    files = request.FILES
    f = files['data']
    data = f.read()
    try: data = data.decode('UTF-8')
    except:
        try: data = data.decode('GBK')
        except: pass

    bills = []

    today = timezone.now()
    p = re.compile("    *")
    for line in data.split("\n"):
        if not line.startswith(u'人民币'):
            continue
        b = Bill()
        vals = p.split(line)
        if vals[3] == u'---':
            vals = [''] + vals
            b.id = vals[2]
            b.date = get_date(vals[2])
            b.stock_money = D(vals[5])
            b.balance = D(vals[6])
            b.name = vals[8]
            if b.stock_money > 0:
                b.type = Bill.TYPES['PUT']
            else:
                b.type = Bill.TYPES['GET']
        else:
            b.id = vals[2]
            b.date = get_date(vals[2])
            b.stock_name = vals[1]
            b.stock_code = vals[13]
            b.stock_price = D(vals[3])
            b.stock_num = D(vals[4])
            b.stock_money = D(vals[5])
            b.balance = D(vals[6])
            b.name = vals[8]
            b.fee1 = D(vals[9])
            b.tax  = D(vals[10])
            b.fee2 = D(vals[11])
            b.fee3 = D(vals[12])
            b.account = vals[14]
            if b.stock_money > 0:
                b.type = Bill.TYPES['SELL']
            else:
                b.type = Bill.TYPES['BUY']

            # 特殊处理转债问题
            if b.stock_code == u'704016':
                b.stock_code = u'110023'
                if b.stock_money == 0:
                    b.stock_money = 0
                    b.stock_num = 1
        if b.date.date() > today.date():
            raise "not large than today"
        b.user = request.user
        b.save()
        bills.append( b )

    request.user.profile.is_outdate = 1
    request.user.profile.save()
    return render(request, 'www/html/import.html', {'bills': bills})

@login_required
def chart_k(request):
    if request.method == 'POST':
        return build(request)
    linetype = request.GET.get('linetype', 0)
    nodes = request.user.node_set.filter(type=Node.TYPES['DAY']).order_by('date').all()
    return render(request, 'www/html/k.html', {'pid': 'chart_k', 'nodes': nodes, 'linetype': linetype})

@login_required
def chart_earn(request):
    return render(request, 'www/html/profile.html', {'pid': 'index'})


