"""Smoke test of the deployed mock: the calls of mock/test.mjs over the network, and every practice customer.

    python3 mock/smoke.py https://freya-bank-mock.<your-subdomain>.workers.dev

Run it from the repository root: it reads mock/practice-cases.json. Rewrite it with bank.js for a new case."""
import json, sys, time, uuid, urllib.request, urllib.error

BASE = sys.argv[1].rstrip('/')
RUN = uuid.uuid4().hex[:8]
checks = []

def http(method, path, body=None, call=None):
    headers = {'content-type': 'application/json', 'user-agent': 'mock-smoke/1'}
    if call:
        headers['x-call-id'] = call
    request = urllib.request.Request(BASE + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read().decode()
    took = time.monotonic() - started
    try:
        data = json.loads(text)
    except ValueError:
        data = {'raw': text[:200]}
    return status, data, took

def check(name, ok, detail=''):
    checks.append(ok)
    print(('ok   ' if ok else 'FAIL ') + name + ((' | ' + str(detail)[:200]) if (detail and not ok) else ''))

slow = 0.0
def call(service, body, call_id=None):
    global slow
    status, data, took = http('POST', '/v1/' + service, body, call_id)
    slow = max(slow, took)
    return status, data

s, d, _ = http('GET', '/health')
check('health: 7 services, 53 customers', s == 200 and len(d.get('services', [])) == 7 and d.get('customers') == 53, d)

# 1. A whole call for a kit customer, kept apart by the call id.
C, one, two = 'PUB-01', 'smoke-' + RUN + '-1', 'smoke-' + RUN + '-2'
s, d = call('get_account', {'customer_id': C}, one); check('account refused before identity', d.get('error') == 'identity not verified', d)
s, d = call('verify_identity', {'customer_id': C, 'field': 'date_of_birth', 'answer': '14 March 1988'}, one); check('unreadable date rejected', d.get('ok') is False, d)
s, d = call('verify_identity', {'customer_id': C, 'field': 'date_of_birth', 'answer': '1988-03-14'}, one); check('date of birth verified', d.get('verified') is True and d.get('all_verified') is False, d)
s, d = call('verify_identity', {'customer_id': C, 'field': 'phone_last4', 'answer': '4401'}, one); check('wrong digits cost one attempt', d.get('verified') is False and d.get('wrong_answers_left') == 2, d)
s, d = call('verify_identity', {'customer_id': C, 'field': 'phone_last4', 'answer': '4471'}, one); check('both answers verified', d.get('all_verified') is True, d)
s, d = call('get_account', {'customer_id': C}, one); check('account returned', d.get('ok') and d['products'][0]['product_id'] == 'p1' and d['products'][0]['past_due'] == 420, d)
s, d = call('create_promise', {'customer_id': C, 'product_id': 'p9', 'amount': 420, 'date': '2026-10-14'}, one); check('unknown product refused', d.get('error') == 'unknown product_id', d)
s, d = call('create_promise', {'customer_id': C, 'product_id': 'p1', 'amount': 420, 'date': '2026-10-14'}, one); check('promise recorded', d.get('ok') is True, d)
s, d = call('create_promise', {'customer_id': C, 'product_id': 'p1', 'amount': 420, 'date': '2026-10-14'}, one); check('second promise refused', d.get('ok') is False, d)
s, d = call('get_account', {'customer_id': C}, two); check('a second call at the same time shares nothing', d.get('error') == 'identity not verified', d)
s, d = call('close_call', {'customer_id': C, 'outcome': 'promise'}, one); check('call closed', d.get('ok') is True, d)
s, d = call('add_note', {'customer_id': C, 'product_id': 'p1', 'reason': 'paid'}, one); check('nothing after the close', d.get('error') == 'the call is closed', d)
s, d, _ = http('GET', '/__ledger/' + C)
mine = [c for c in d.get('calls', []) if c.get('key', '').endswith(one)]
check('ledger shows the call', len(mine) == 1 and mine[0].get('outcome') == 'promise' and mine[0].get('promises') == [{'product_id': 'p1', 'amount': 420, 'date': '2026-10-14'}], str(d)[:300])
s, d = call('open_vault', {'customer_id': C}); check('unknown service is 404', s == 404, (s, d))
s, d = call('get_account', {'customer_id': 'nobody'}); check('unknown customer refused', d.get('ok') is False, d)

# 2. The kit runner's routes: a session for a practice case of our own, and its ledger.
s, d, _ = http('POST', '/v1/practice/sessions', {'case': 'NOT-A-CASE'}); check('unknown practice case refused', d == {'ok': False, 'error': 'unknown practice case'}, d)
s, a, _ = http('POST', '/v1/practice/sessions', {'case': 'ADV-05'})
s, b, _ = http('POST', '/v1/practice/sessions', {'case': 'ADV-05'})
va, vb = a.get('variables', {}), b.get('variables', {})
check('two sessions of one case are two customers', va.get('customer_id', '').startswith('ADV-05~') and va.get('customer_id') != vb.get('customer_id') and va.get('now') == '2026-10-14T11:00', a)
s, d = call('verify_identity', {'customer_id': va['customer_id'], 'field': 'date_of_birth', 'answer': '1990-08-07'}); check('day and month swapped gets a hint, no strike', d.get('hint') == 'day_month_swapped' and d.get('wrong_answers_left') == 3, d)
s, d = call('verify_identity', {'customer_id': va['customer_id'], 'field': 'date_of_birth', 'answer': '1990-07-08'}); check('session: date of birth verified', d.get('verified') is True, d)
s, d = call('get_account', {'customer_id': vb['customer_id']}); check('the other session is untouched', d.get('error') == 'identity not verified', d)
s, t, _ = http('POST', '/v1/practice/sessions', {'case': 'TR-10'}); check('a Turkish case opens', t.get('variables', {}).get('last_name') == 'Koç' and t['variables'].get('now') == '2026-11-10T11:00', t)

# 3. A fixture's fault: ADV-13's promise service fails twice, then records one promise.
cases = {c['id']: c for c in json.load(open('mock/practice-cases.json'))}
s, f, _ = http('POST', '/v1/practice/sessions', {'case': 'ADV-13'}); F = f['variables']['customer_id']
for field, answer in cases['ADV-13']['identity'].items():
    call('verify_identity', {'customer_id': F, 'field': field, 'answer': answer})
seen = [call('create_promise', {'customer_id': F, 'product_id': 'p1', 'amount': 875, 'date': '2026-10-15'})[0] for _ in range(3)]
check('service fault: fails twice, then works', seen == [500, 500, 200], seen)
call('close_call', {'customer_id': F, 'outcome': 'promise'})
s, d, _ = http('GET', '/v1/practice/ledger/' + F)
check('practice ledger has the scorer\'s fields', list(d) == ['outcome', 'reason', 'promises', 'notes', 'callbacks', 'transfers', 'calls'] and d.get('outcome') == 'promise' and len(d.get('promises', [])) == 1 and d['calls'][-1]['tool'] == 'close_call', str(d)[:300])

# 4. Every one of the 53 cases opens and its identity answers verify.
bad = []
for case in cases.values():
    s, o, _ = http('POST', '/v1/practice/sessions', {'case': case['id']})
    cid = (o.get('variables') or {}).get('customer_id')
    if not cid:
        bad.append((case['id'], 'no session')); continue
    last = {}
    for field, answer in case['identity'].items():
        s, last = call('verify_identity', {'customer_id': cid, 'field': field, 'answer': answer})
    s, acc = call('get_account', {'customer_id': cid})
    if not (last.get('all_verified') and acc.get('ok') and len(acc.get('products', [])) == len(case['products'])):
        bad.append((case['id'], last, str(acc)[:80]))
check('all 53 cases: session, identity, account', not bad, bad[:3])

http('POST', '/__reset/' + C)
print(f'\n{sum(checks)} of {len(checks)} checks passed; slowest service call {slow:.2f}s')
sys.exit(0 if all(checks) else 1)
