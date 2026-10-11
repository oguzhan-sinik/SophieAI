"""Smoke test of the deployed statement services: every answer the bank's file lists, over the network.

    python3 mock/smoke_statement.py https://freya-bank-mock.<your-subdomain>.workers.dev "<case folder>/test-environment/test-customers.json"

One answer in the data is delayed by 12 seconds; the run takes about two minutes."""
import json, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE, SOURCE = sys.argv[1].rstrip('/'), sys.argv[2]

def call(service, data):
    request = urllib.request.Request(BASE + '/voice/v1/' + service, method='POST', headers={'content-type': 'application/json', 'user-agent': 'mock-smoke/1'},
                                     data=json.dumps({'data': data, 'call': {'ani': '', 'lang': 'tr'}}).encode())
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode()
    return status, json.loads(text), time.monotonic() - started

jobs = []
for customer in json.load(open(SOURCE, encoding='utf-8'))['customers']:
    s, no = customer['services'], customer['customerNo']
    jobs.append(('cards.list', {'customerNo': no, 'aiFlow': 'CardOps'}, s['cards.list']))
    jobs.append(('contact.email.get', {'customerNo': int(no), 'intAddressInfoType': 'E'}, s['contact.email.get']))
    if 'statement.pdf.send' in s:
        jobs.append(('statement.pdf.send', {'customerNo': no, 'cardNumber': 'x', 'currencyType': 'TL', 'statementDate': '05.10.2026', 'emailAddress': 'a@b.example'}, s['statement.pdf.send']))
    for service in ('cards.balance', 'statement.week.get'):
        jobs += [(service, {'cardNumber': card}, entry) for card, entry in s.get(service, {}).items()]
    for service in ('statement.week.decide', 'statement.week.change'):
        jobs += [(service, {'cardNumber': card, 'newStatementWeek': int(week), 'statementDay': 5}, entry) for card, weeks in s.get(service, {}).items() for week, entry in weeks.items()]

def check(job):
    service, data, entry = job
    status, body, took = call(service, data)
    ok = status == entry['http'] and body == entry['response'] and took >= entry.get('delaySeconds', 0)
    return ok, service, data, status, took

bad, slowest = [], 0.0
with ThreadPoolExecutor(8) as pool:
    for ok, service, data, status, took in pool.map(check, jobs):
        slowest = max(slowest, took)
        if not ok:
            bad.append((service, data, status))
for service, data, want in (('cards.list', {'customerNo': '11111111'}, (404, 'FB_IVR_CHANNEL_102')), ('cards.balance', {'cardNumber': '540000******0000'}, (404, 'FB_IVR_CHANNEL_120')),
                            ('statement.week.get', {'cardNumber': '540000******0000'}, (404, 'FB_IVR_CHANNEL_121')), ('statement.pdf.send', {'customerNo': '11111111'}, (404, 'FB_IVR_CHANNEL_107')),
                            ('statement.week.change', {'cardNumber': '540000******1234', 'newStatementWeek': 1, 'statementDay': 5}, (400, 'INVALID_ARGUMENTS_ERROR')),
                            ('contact.email.get', {'customerNo': '90000001', 'intAddressInfoType': ''}, (400, 'INVALID_ARGUMENTS_ERROR'))):
    status, body, _ = call(service, data)
    if (status, body.get('result', {}).get('code')) != want or 'data' in body:
        bad.append((service, data, status))
print(f'{len(jobs) + 6 - len(bad)} of {len(jobs) + 6} answers as listed; slowest answer {slowest:.1f}s')
for item in bad[:10]:
    print('  WRONG', item)
sys.exit(1 if bad else 0)
