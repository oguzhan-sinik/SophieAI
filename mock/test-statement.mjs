// The final case's services, without Cloudflare:
//   node mock/test-statement.mjs "<case folder>/test-environment/test-customers.json"
// Every answer the bank's file lists must come back exactly, status code included.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import worker, { Session } from './src/worker.js';

class Storage {
  constructor() { this.values = new Map(); }
  async get(key) { return this.values.has(key) ? structuredClone(this.values.get(key)) : undefined; }
  async put(key, value) { this.values.set(key, structuredClone(value)); }
  async deleteAll() { this.values.clear(); }
}
const objects = new Map();
const env = {
  NO_DELAY: true,
  SESSION: {
    idFromName: (name) => name,
    get(id) {
      if (!objects.has(id)) objects.set(id, new Session({ storage: new Storage() }, env));
      return { fetch: (url, init) => objects.get(id).fetch(new Request(url, init)) };
    },
  },
};
const pending = [];
const ctx = { waitUntil: (promise) => pending.push(promise) };

async function call(service, data, prefix = '/voice/v1/') {
  const body = JSON.stringify({ data, call: { ani: '', lang: 'tr' } });
  const response = await worker.fetch(new Request('https://mock.example' + prefix + service, { method: 'POST', headers: { 'content-type': 'application/json' }, body }), env, ctx);
  return { status: response.status, body: await response.json() };
}

const source = JSON.parse(readFileSync(process.argv[2], 'utf8'));
let checked = 0;
const same = (got, entry, what) => { assert.equal(got.status, entry.http, what); assert.deepEqual(got.body, entry.response, what); checked += 1; };
for (const customer of source.customers) {
  const s = customer.services;
  const no = customer.customerNo;
  same(await call('cards.list', { customerNo: no, aiFlow: 'CardOps' }), s['cards.list'], `cards.list ${no}`);
  same(await call('cards.list', { customerNo: Number(no), aiFlow: 'CardOps' }), s['cards.list'], `cards.list ${no} as a number`);
  same(await call('contact.email.get', { customerNo: Number(no), intAddressInfoType: 'E' }), s['contact.email.get'], `contact.email.get ${no}`);
  if (s['statement.pdf.send']) {
    same(await call('statement.pdf.send', { customerNo: no, cardNumber: 'x', currencyType: 'TL', statementDate: '05.10.2026', emailAddress: 'a@b.example' }), s['statement.pdf.send'], `statement.pdf.send ${no}`);
  } else {
    const got = await call('statement.pdf.send', { customerNo: no, cardNumber: 'x', currencyType: 'TL', statementDate: '05.10.2026', emailAddress: 'a@b.example' });
    assert.deepEqual([got.status, got.body.result.code, got.body.data], [404, 'FB_IVR_CHANNEL_107', undefined], `no statement.pdf.send entry for ${no}`);
  }
  for (const service of ['cards.balance', 'statement.week.get']) {
    for (const [card, entry] of Object.entries(s[service] || {})) same(await call(service, { cardNumber: card }), entry, `${service} ${card}`);
  }
  for (const service of ['statement.week.decide', 'statement.week.change']) {
    for (const [card, weeks] of Object.entries(s[service] || {})) {
      for (const [week, entry] of Object.entries(weeks)) {
        same(await call(service, { cardNumber: card, newStatementWeek: Number(week), statementDay: 5 }), entry, `${service} ${card} week ${week}`);
        same(await call(service, { cardNumber: card, newStatementWeek: week, statementDay: 5 }, '/'), entry, `${service} ${card} week "${week}" without a prefix`);
      }
      // The card's own week has no entry: an error, never made-up dates.
      const own = ['1', '2', '3', '4'].find((w) => !Object.hasOwn(weeks, w));
      const got = await call(service, { cardNumber: card, newStatementWeek: own, statementDay: 5 });
      assert.deepEqual([got.status, got.body.result.code, got.body.data], [400, 'INVALID_ARGUMENTS_ERROR', undefined], `${service} ${card} own week`);
    }
  }
}

// What is not in the file: the service's 404 where the contract has one, else a 400. Error answers carry no data.
const error = async (service, data, status, code, type) => {
  const got = await call(service, data);
  assert.deepEqual([got.status, got.body.result.code, got.body.result.returnCode, got.body.result.type, 'data' in got.body], [status, code, code, type, false], `${service} ${JSON.stringify(data)}`);
  assert.equal(got.body.result.message, got.body.result.messageText);
};
await error('cards.list', { customerNo: '11111111' }, 404, 'FB_IVR_CHANNEL_102', 'WARNING');
await error('cards.list', { customerNo: '{{customerNumber}}' }, 404, 'FB_IVR_CHANNEL_102', 'WARNING');
await error('cards.list', {}, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('cards.balance', { cardNumber: '540000******0000' }, 404, 'FB_IVR_CHANNEL_120', 'WARNING');
await error('cards.balance', { cardNumber: '5400********1234' }, 404, 'FB_IVR_CHANNEL_120', 'WARNING');   // the balance answer's own masking is no card number
await error('cards.balance', { cardNumber: '' }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('statement.week.get', { cardNumber: '540000******0000' }, 404, 'FB_IVR_CHANNEL_121', 'WARNING');
await error('statement.week.decide', { cardNumber: '540000******0000', newStatementWeek: 2, statementDay: 5 }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('statement.week.change', { cardNumber: '540000******1234', statementDay: 5 }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('statement.week.change', { cardNumber: '540000******1234', newStatementWeek: 7, statementDay: 5 }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('contact.email.get', { customerNo: '11111111', intAddressInfoType: 'E' }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('contact.email.get', { customerNo: '90000001', intAddressInfoType: '' }, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR');
await error('statement.pdf.send', { customerNo: '11111111' }, 404, 'FB_IVR_CHANNEL_107', 'WARNING');
let response = await worker.fetch(new Request('https://mock.example/voice/v1/cards.list', { method: 'POST', body: 'not json' }), env, ctx);
assert.equal(response.status, 400);
response = await worker.fetch(new Request('https://mock.example/voice/v1/cards.list'), env, ctx);
assert.equal(response.status, 405);

// The delayed answer is marked in the data, and the recorder kept what was asked.
const { answer } = await import('./src/statement.js');
assert.equal(answer('cards.balance', { data: { cardNumber: '540000******7211' } }).delaySeconds, 12);
await Promise.all(pending);
const recent = await (await worker.fetch(new Request('https://mock.example/__recent'), env, ctx)).json();
assert.equal(recent.requests.length, 200);
assert.deepEqual(Object.keys(recent.requests.at(-1)), ['at', 'service', 'path', 'body', 'status']);
const health = await (await worker.fetch(new Request('https://mock.example/health'), env, ctx)).json();
assert.equal(health.services.length, 14);

console.log(`statement mock: ${checked} listed answers returned exactly; all checks passed`);
