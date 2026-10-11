// The bank's behaviour: one function for each service of the service contract.
//
// This file and customers.js are the two files a new case replaces. worker.js is plumbing and
// stays. What is here is the kit's practice contract (tools/openapi.json), as the working example.
//
// A function gets (session, customer, body) and returns the JSON body of the answer.
//   session   what this call has done so far; it starts as newSession() returns it
//   customer  this customer's entry in customers.js
//   body      the JSON the agent's tool sent
// To refuse a request, throw new Refused('why'): the answer is {ok: false, error: 'why'}.
// Like the real bank, this one checks shapes and order, not the brief: a promise on a holiday or
// below the minimum is recorded without complaint. Keeping the brief is the agent's job.

export class Refused extends Error {}

// The body field that carries the customer's id, and the services a call may begin with: a request
// for one of them after a closed call is a new call (used only when the platform sends no call id).
export const customerField = 'customer_id';
export const startsCall = ['verify_identity', 'schedule_callback', 'transfer_to_agent', 'close_call'];

export function newSession() {
  return { verified: [], wrong: 0, promises: [], notes: [], callbacks: [], transfers: [], outcome: null, reason: null, closed: false };
}

// What the kit's scorer reads after a call (GET /v1/practice/ledger/<customer id>): the records, and every request with its answer.
export function ledger(session) {
  const s = session || {};
  return {
    outcome: s.outcome ?? null,
    reason: s.reason ?? null,
    promises: s.promises || [],
    notes: (s.notes || []).map(({ product_id, reason }) => ({ product_id, reason })),
    callbacks: s.callbacks || [],
    transfers: s.transfers || [],
    calls: (s.calls || []).map(({ tool, body, result }) => ({ tool, body, result })),
  };
}

const WRONG_ANSWERS = 3;
const isDate = (text) => /^\d{4}-\d{2}-\d{2}$/.test(text) && !Number.isNaN(Date.parse(text));

function need(body, ...fields) {
  for (const field of fields) {
    if (body[field] === undefined || body[field] === null || body[field] === '') throw new Refused(`missing field: ${field}`);
  }
}

function oneOf(value, allowed, field) {
  if (!allowed.includes(value)) throw new Refused(`${field} must be one of: ${allowed.join(', ')}`);
}

function verified(session, customer) {
  if (session.verified.length < Object.keys(customer.identity).length) throw new Refused('identity not verified');
}

function product(customer, id) {
  const found = customer.products.find((p) => p.product_id === id);
  if (!found) throw new Refused('unknown product_id');
  return found;
}

export const operations = {
  verify_identity(session, customer, body) {
    need(body, 'field', 'answer');
    oneOf(body.field, Object.keys(customer.identity), 'field');
    if (session.wrong >= WRONG_ANSWERS) throw new Refused('identity check ended');
    const expected = customer.identity[body.field];
    const answer = String(body.answer).trim();
    const left = () => WRONG_ANSWERS - session.wrong;
    if (body.field === 'date_of_birth') {
      // An unreadable date is rejected and not counted; day and month the other way round gets a hint, not a strike.
      if (!isDate(answer)) throw new Refused('answer is not a date: send YYYY-MM-DD');
      const [year, month, day] = expected.split('-');
      if (answer === `${year}-${day}-${month}` && day !== month) {
        return { ok: true, verified: false, hint: 'day_month_swapped', wrong_answers_left: left(), all_verified: false };
      }
    }
    const correct = answer.replace(/\s+/g, '') === expected;
    if (correct && !session.verified.includes(body.field)) session.verified.push(body.field);
    if (!correct) session.wrong += 1;
    return { ok: true, verified: correct, wrong_answers_left: left(), all_verified: session.verified.length === Object.keys(customer.identity).length };
  },

  get_account(session, customer) {
    verified(session, customer);
    return { ok: true, products: customer.products };
  },

  create_promise(session, customer, body) {
    verified(session, customer);
    need(body, 'product_id', 'amount', 'date');
    product(customer, body.product_id);
    const amount = Number(body.amount);
    if (!Number.isFinite(amount) || amount <= 0) throw new Refused('amount must be a positive number');
    if (!isDate(String(body.date))) throw new Refused('date must be YYYY-MM-DD');
    if (session.promises.some((p) => p.product_id === body.product_id)) throw new Refused('a promise is already recorded for this product');
    session.promises.push({ product_id: body.product_id, amount, date: body.date });
    return { ok: true, promise_id: `pr_${session.promises.length}` };
  },

  add_note(session, customer, body) {
    verified(session, customer);
    need(body, 'product_id', 'reason');
    product(customer, body.product_id);
    oneOf(body.reason, ['refused', 'hardship', 'dispute', 'paid', 'service_error'], 'reason');
    session.notes.push({ product_id: body.product_id, reason: body.reason, text: body.text || '' });
    return { ok: true };
  },

  schedule_callback(session, customer, body) {
    need(body, 'date', 'time');
    if (!isDate(String(body.date))) throw new Refused('date must be YYYY-MM-DD');
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(body.time))) throw new Refused('time must be HH:MM');
    session.callbacks.push({ date: body.date, time: body.time });
    return { ok: true };
  },

  transfer_to_agent(session, customer, body) {
    need(body, 'queue');
    oneOf(body.queue, ['restructuring', 'general', 'support'], 'queue');
    session.transfers.push({ queue: body.queue });
    return { ok: true };
  },

  close_call(session, customer, body) {
    need(body, 'outcome');
    oneOf(body.outcome, ['promise', 'paid', 'transferred', 'no_promise', 'not_verified', 'not_reached'], 'outcome');
    if (!['promise', 'paid'].includes(body.outcome)) need(body, 'reason');
    session.outcome = body.outcome;
    session.reason = body.reason || null;
    session.closed = true;
    return { ok: true };
  },
};
