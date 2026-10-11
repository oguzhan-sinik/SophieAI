// A mock of a bank's services on Cloudflare Workers. This file is plumbing and knows no bank:
// routing, JSON, one Durable Object for each call, and a record of every request.
// The bank's behaviour is in bank.js, its customers in customers.js.
//
//   POST <any prefix>/<service>      a service of the contract; the body is JSON
//   GET  /health                     what this mock serves
//   GET  /__ledger/<customer id>     what the calls for this customer did (for your own tests)
//   POST /__reset/<customer id>      forget the calls for this customer (for your own tests)
//
// The two routes the kit's runner uses, so that tools/run_cases.py can test an agent against this
// bank with practice cases of your own (FREYA_BANK_HOST=<this mock>):
//   POST <any prefix>/practice/sessions          {"case": "<case id>"} opens a fresh customer for the case
//   GET  <any prefix>/practice/ledger/<customer> what that customer's call left behind
//
// One call, one state. A workflow built with a mock address sends the platform's call id in the
// header X-Call-Id, and each call then has its own Durable Object: two calls for the same customer
// never share a strike or a promise, and a read always sees the write before it. Without the
// header the state is the customer's, and a call that begins after a closed one starts afresh.

import { Refused, customerField, ledger, newSession, operations, startsCall } from './bank.js';
import customers from './customers.js';

const IDLE_MS = 30 * 60 * 1000;      // a call left open this long is over
const CLOSED_MS = 20 * 1000;         // nothing is accepted after a call closed; this long after it, a request is a new call
const HEADERS = { 'content-type': 'application/json; charset=utf-8', 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' };

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: HEADERS });

// A placeholder the platform did not fill in is no call id.
function callId(request) {
  const value = (request.headers.get('x-call-id') || '').trim();
  return value && !value.includes('{') && value.length <= 200 ? value : '';
}

// A practice session's customer id is "<case id>~<random>": its fixture is the case's, its state its own.
const fixture = (id) => (Object.hasOwn(customers, id) ? customers[id] : Object.hasOwn(customers, id.split('~')[0]) && id.includes('~') ? customers[id.split('~')[0]] : null);

const stub = (env, name) => env.SESSION.get(env.SESSION.idFromName(name));
const ask = (env, name, path, body) => stub(env, name).fetch('https://session/' + path, { method: 'POST', body: JSON.stringify(body || {}) });

export default {
  async fetch(request, env) {
    const parts = new URL(request.url).pathname.split('/').filter(Boolean);
    const last = parts[parts.length - 1] || '';
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: HEADERS });
    if (request.method === 'GET' && (parts.length === 0 || last === 'health')) {
      return json({ ok: true, services: Object.keys(operations), customers: Object.keys(customers).length });
    }
    if (parts.length >= 2 && parts[parts.length - 2] === '__ledger' && request.method === 'GET') {
      const index = await (await ask(env, 'index|' + last, '__index')).json();
      const calls = [];
      for (const key of index.calls) calls.push({ key, ...(await (await ask(env, key, '__ledger')).json()) });
      return json({ customer: last, calls });
    }
    if (parts.length >= 2 && parts[parts.length - 2] === '__reset' && request.method === 'POST') {
      const index = await (await ask(env, 'index|' + last, '__index')).json();
      for (const key of [last, ...index.calls]) await ask(env, key, '__reset');
      await ask(env, 'index|' + last, '__reset');
      return json({ ok: true });
    }
    const before = parts[parts.length - 2] || '';
    if (before === 'practice' && last === 'sessions' && request.method === 'POST') {
      const asked = await request.json().catch(() => ({}));
      const name = String((asked && asked.case) || '');
      if (!Object.hasOwn(customers, name)) return json({ ok: false, error: 'unknown practice case' });
      return json({ ok: true, variables: { ...customers[name].variables, [customerField]: `${name}~${crypto.randomUUID().slice(0, 8)}` } });
    }
    if (parts[parts.length - 3] === 'practice' && before === 'ledger' && request.method === 'GET') {
      return json(ledger(await (await ask(env, last, '__ledger')).json()));
    }
    if (!Object.hasOwn(operations, last)) return json({ ok: false, error: `unknown service: ${last || '(none)'}` }, 404);
    if (request.method !== 'POST') return json({ ok: false, error: 'send a POST with a JSON body' }, 405);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ ok: false, error: 'the body must be JSON' }, 400);
    }
    if (body === null || typeof body !== 'object' || Array.isArray(body)) return json({ ok: false, error: 'the body must be a JSON object' }, 400);
    const customerId = String(body[customerField] ?? '');
    if (!fixture(customerId)) return json({ ok: false, error: `unknown ${customerField}` });
    // A practice session is one call already; anything else is kept apart by the platform's call id.
    const call = customerId.includes('~') ? '' : callId(request);
    const key = call ? `${customerId}|${call}` : customerId;
    return ask(env, key, last, { body, customerId, key });
  },
};

export class Session {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request) {
    const path = new URL(request.url).pathname.slice(1);
    const input = await request.json();
    const storage = this.state.storage;
    if (path === '__index') {
      // This object is a customer's list of calls, not a call.
      const calls = (await storage.get('calls')) || [];
      if (input.add && !calls.includes(input.add)) {
        calls.push(input.add);
        await storage.put('calls', calls.slice(-50));
      }
      return json({ calls });
    }
    if (path === '__ledger') return json((await storage.get('session')) || { calls: [] });
    if (path === '__reset') {
      await storage.deleteAll();
      return json({ ok: true });
    }
    const { body, customerId, key } = input;
    const customer = fixture(customerId);
    const now = Date.now();
    let session = await storage.get('session');
    const over = session && (now - session.touched > IDLE_MS || (session.closed && (startsCall.includes(path) || now - session.touched > CLOSED_MS)));
    if (!session || over) {
      session = { ...newSession(customer), opened: new Date(now).toISOString(), calls: [] };
      await ask(this.env, 'index|' + customerId, '__index', { add: key });
    }
    let result;
    let status = 200;
    try {
      if (session.closed) throw new Refused('the call is closed');
      // A fixture may say that a service fails the first n times it is called.
      const fault = (customer.faults || []).find((f) => f.tool === path);
      const before = session.calls.filter((c) => c.tool === path).length;
      if (fault && before < fault.fail_first_n) {
        status = 500;
        result = { ok: false, error: 'the service failed; nothing was recorded' };
      } else {
        result = operations[path](session, customer, body);
      }
    } catch (error) {
      // A refusal is an answer. Anything else is a mistake in bank.js, shown as it is.
      result = { ok: false, error: error instanceof Refused ? error.message : `mock error: ${error && error.message}` };
      if (!(error instanceof Refused)) status = 500;
    }
    session.calls.push({ tool: path, body, result, status, at: new Date(now).toISOString() });
    session.touched = now;
    await storage.put('session', session);
    return json(result, status);
  }
}
