// Run the mock without Cloudflare:  node mock/test.mjs
// It drives the Worker through its own fetch handler, with Durable Objects kept in memory.
// The calls below are the practice contract; rewrite them with bank.js for a new case.
import assert from 'node:assert/strict';
import worker, { Session } from './src/worker.js';

class Storage {
  constructor() { this.values = new Map(); }
  async get(key) { return this.values.has(key) ? structuredClone(this.values.get(key)) : undefined; }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
  async deleteAll() { this.values.clear(); }
}

const objects = new Map();
const env = {
  SESSION: {
    idFromName: (name) => name,
    get(id) {
      if (!objects.has(id)) objects.set(id, new Session({ storage: new Storage() }, env));
      return { fetch: (url, init) => objects.get(id).fetch(new Request(url, init)) };
    },
  },
};

const BASE = 'https://mock.example/v1/';
async function call(service, body, callId) {
  const headers = { 'content-type': 'application/json', ...(callId ? { 'x-call-id': callId } : {}) };
  const response = await worker.fetch(new Request(BASE + service, { method: 'POST', headers, body: JSON.stringify(body) }), env);
  return { status: response.status, ...(await response.json()) };
}
const get = async (path) => (await worker.fetch(new Request('https://mock.example' + path), env)).json();

const C = 'PUB-01';   // date of birth 1988-03-14, phone 4471, one credit card with 420 past due

// A whole call: identity, account, promise, close.
let r = await call('get_account', { customer_id: C }, 'call-1');
assert.deepEqual([r.ok, r.error], [false, 'identity not verified']);
r = await call('verify_identity', { customer_id: C, field: 'date_of_birth', answer: '14 March 1988' }, 'call-1');
assert.equal(r.ok, false);                                  // unreadable date: rejected, not counted
r = await call('verify_identity', { customer_id: C, field: 'date_of_birth', answer: '1988-14-03' }, 'call-1');
assert.equal(r.ok, false);                                  // not a date at all
r = await call('verify_identity', { customer_id: C, field: 'date_of_birth', answer: '1988-03-14' }, 'call-1');
assert.deepEqual([r.verified, r.all_verified, r.wrong_answers_left], [true, false, 3]);
r = await call('verify_identity', { customer_id: C, field: 'phone_last4', answer: '4401' }, 'call-1');
assert.deepEqual([r.verified, r.wrong_answers_left], [false, 2]);
r = await call('verify_identity', { customer_id: C, field: 'phone_last4', answer: '4471' }, 'call-1');
assert.deepEqual([r.verified, r.all_verified], [true, true]);
r = await call('get_account', { customer_id: C }, 'call-1');
assert.equal(r.products[0].product_id, 'p1');
assert.equal(r.products[0].past_due, 420);
r = await call('create_promise', { customer_id: C, product_id: 'p9', amount: 420, date: '2026-10-14' }, 'call-1');
assert.equal(r.error, 'unknown product_id');
r = await call('create_promise', { customer_id: C, product_id: 'p1', amount: 420, date: '2026-10-14' }, 'call-1');
assert.equal(r.ok, true);
r = await call('create_promise', { customer_id: C, product_id: 'p1', amount: 420, date: '2026-10-14' }, 'call-1');
assert.equal(r.ok, false);                                  // one promise for each product
r = await call('close_call', { customer_id: C, outcome: 'no_promise' }, 'call-1');
assert.equal(r.ok, false);                                  // a reason is required
r = await call('close_call', { customer_id: C, outcome: 'promise' }, 'call-1');
assert.equal(r.ok, true);
r = await call('add_note', { customer_id: C, product_id: 'p1', reason: 'paid' }, 'call-1');
assert.equal(r.error, 'the call is closed');                // nothing after the close

// A second call for the same customer at the same time shares nothing with the first.
r = await call('get_account', { customer_id: C }, 'call-2');
assert.equal(r.error, 'identity not verified');

// Three wrong answers end the check; day and month the other way round is a hint, not a strike.
r = await call('verify_identity', { customer_id: C, field: 'date_of_birth', answer: '1988-03-15' }, 'call-2');
r = await call('verify_identity', { customer_id: 'PUB-12', field: 'date_of_birth', answer: '1983-19-10' }, 'call-3');
assert.equal(r.ok, false);
r = await call('verify_identity', { customer_id: 'PUB-04', field: 'date_of_birth', answer: '1984-30-01' }, 'call-4');
assert.equal(r.ok, false);                                  // month 30 is no date
r = await call('verify_identity', { customer_id: 'PUB-07', field: 'date_of_birth', answer: '1975-05-12' }, 'call-5');
assert.deepEqual([r.hint, r.wrong_answers_left], ['day_month_swapped', 3]);
for (const answer of ['0000', '1111']) await call('verify_identity', { customer_id: C, field: 'phone_last4', answer }, 'call-2');
r = await call('verify_identity', { customer_id: C, field: 'phone_last4', answer: '4471' }, 'call-2');
assert.equal(r.error, 'identity check ended');

// A fixture's fault: the promise service fails once, then works, and records one promise.
const F = 'PUB-10';
await call('verify_identity', { customer_id: F, field: 'date_of_birth', answer: '1989-02-23' }, 'call-6');
await call('verify_identity', { customer_id: F, field: 'phone_last4', answer: '9904' }, 'call-6');
r = await call('create_promise', { customer_id: F, product_id: 'p1', amount: 365, date: '2026-10-16' }, 'call-6');
assert.equal(r.status, 500);
r = await call('create_promise', { customer_id: F, product_id: 'p1', amount: 365, date: '2026-10-16' }, 'call-6');
assert.equal(r.ok, true);

// Without a call id the state is the customer's, and a call that begins after a closed one starts afresh.
const P = 'PUB-08';
for (const callHeader of [undefined, '{{call.call_id}}']) {    // a placeholder the platform did not fill in is no call id
  await call('verify_identity', { customer_id: P, field: 'date_of_birth', answer: '1993-04-28' }, callHeader);
  await call('verify_identity', { customer_id: P, field: 'phone_last4', answer: '3317' }, callHeader);
  r = await call('close_call', { customer_id: P, outcome: 'paid' }, callHeader);
  assert.equal(r.ok, true);
  r = await call('get_account', { customer_id: P }, callHeader);
  assert.equal(r.error, 'the call is closed');
}

// What the mock recorded, and the answers to requests it cannot serve.
let ledger = await get('/__ledger/' + C);
assert.equal(ledger.calls.length, 2);
assert.deepEqual(ledger.calls[0].promises, [{ product_id: 'p1', amount: 420, date: '2026-10-14' }]);
assert.equal(ledger.calls[0].outcome, 'promise');
assert.equal(ledger.calls[0].calls.at(-1).tool, 'add_note');
ledger = await get('/__ledger/' + P);
assert.equal(ledger.calls.length, 1);
assert.equal(ledger.calls[0].calls.length, 4);              // the second call replaced the first
r = await call('get_account', { customer_id: 'nobody' });
assert.equal(r.ok, false);
r = await call('open_vault', { customer_id: C });
assert.equal(r.status, 404);
r = await get('/health');
assert.equal(r.services.length, 14);          // the practice bank and the statement services
assert.equal(r.customers, 53);

// The kit runner's two routes: a fresh customer for a case, and what its call left behind.
const open = async (name) => (await worker.fetch(new Request(BASE + 'practice/sessions', { method: 'POST', body: JSON.stringify({ case: name }) }), env)).json();
r = await open('NOT-A-CASE');
assert.deepEqual(r, { ok: false, error: 'unknown practice case' });
const first = (await open('ADV-05')).variables;
const second = (await open('ADV-05')).variables;
assert.deepEqual([first.first_name, first.now], ['Mia', '2026-10-14T11:00']);
assert.notEqual(first.customer_id, second.customer_id);
r = await call('verify_identity', { customer_id: first.customer_id, field: 'date_of_birth', answer: '1990-08-07' }, 'ignored-for-a-session');
assert.equal(r.hint, 'day_month_swapped');                 // said as 07/08: day and month the other way round
r = await call('verify_identity', { customer_id: first.customer_id, field: 'date_of_birth', answer: '1990-07-08' });
assert.equal(r.verified, true);
r = await call('get_account', { customer_id: second.customer_id });
assert.equal(r.error, 'identity not verified');            // the second session of the same case shares nothing
const TR = (await open('TR-10')).variables;
assert.deepEqual([TR.last_name, TR.now], ['Koç', '2026-11-10T11:00']);
const two = (await open('ADV-13')).variables;                // the promise service fails twice
const answers = (await import('./src/customers.js')).default['ADV-13'].identity;
await call('verify_identity', { customer_id: two.customer_id, field: 'date_of_birth', answer: answers.date_of_birth });
await call('verify_identity', { customer_id: two.customer_id, field: 'phone_last4', answer: answers.phone_last4 });
for (const expected of [500, 500, 200]) {
  r = await call('create_promise', { customer_id: two.customer_id, product_id: 'p1', amount: 875, date: '2026-10-15' });
  assert.equal(r.status, expected);
}
await call('close_call', { customer_id: two.customer_id, outcome: 'promise' });
let kept = await get('/v1/practice/ledger/' + two.customer_id);
assert.deepEqual(Object.keys(kept), ['outcome', 'reason', 'promises', 'notes', 'callbacks', 'transfers', 'calls']);
assert.deepEqual([kept.outcome, kept.reason, kept.promises.length, kept.calls.length, kept.calls.at(-1).tool], ['promise', null, 1, 6, 'close_call']);
kept = await get('/v1/practice/ledger/' + second.customer_id);
assert.equal(kept.calls[0].result.error, 'identity not verified');
kept = await get('/v1/practice/ledger/PUB-01~neveropened');
assert.deepEqual([kept.outcome, kept.calls.length], [null, 0]);
await worker.fetch(new Request('https://mock.example/__reset/' + C, { method: 'POST' }), env);
assert.equal((await get('/__ledger/' + C)).calls.length, 0);

console.log('mock: all checks passed');
