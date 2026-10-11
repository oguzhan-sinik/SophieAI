# Mock of the bank's services

A Cloudflare Worker that stands in for the bank while the phone agent is tested. In the final the
agent's tools call this mock, so it must be right and it must stay up until the results are out.

| File | What it is | For a new case |
|---|---|---|
| `src/worker.js` | Plumbing: routing, JSON, one state per call, a record of every request | Stays as it is |
| `src/bank.js` | The bank's behaviour, one function per service | Rewrite from the service contract |
| `src/customers.js` | The fixtures, one entry per customer id | Rewrite from the bank's test customers |
| `test.mjs` | Checks that run without Cloudflare | Rewrite with `bank.js` |

What ships here is the kit's practice contract with the 53 practice cases of
`public-plus-adversarial-53.json` (the kit's thirteen and forty more), as a working example. All of
it is synthetic.

## Test it here

```bash
node mock/test.mjs
```

## Deploy it

Needs a Cloudflare account. The first command opens a browser to sign in.

```bash
cd mock && npx wrangler login
```

```bash
cd mock && npx wrangler deploy
```

`wrangler deploy` prints the address, `https://freya-bank-mock.<your-subdomain>.workers.dev`. That
address is the `mock_url` of the build and of `submission.json`:

```bash
python3 agent/builder/build.py <case_folder> https://freya-bank-mock.<your-subdomain>.workers.dev 2>&1 | tee traces/final.log
```

Check it once it is up:

```bash
curl https://freya-bank-mock.<your-subdomain>.workers.dev/health
```

```bash
python3 mock/smoke.py https://freya-bank-mock.<your-subdomain>.workers.dev
```

The second runs a whole call, two calls at once, a service fault and all 53 practice customers
against the deployed mock.

## Practice cases of your own

The organisers' practice bank knows its own thirteen customers and answers "unknown practice case"
for any other. A case of your own needs a bank that knows it: this mock. It serves the two routes
the kit's runner uses (`/v1/practice/sessions` and `/v1/practice/ledger/<customer>`), so the kit's
runner and scorer work with it unchanged.

Write the fixtures from a case file in the kit's shape (it may lack the security answers; they are
filled in), then deploy again:

```bash
python3 mock/make_fixtures.py ~/Downloads/public-plus-adversarial-53.json
```

That writes `mock/src/customers.js` for the mock and `mock/practice-cases.json` for the runner.

Build with those cases in place of the kit's thirteen. The agent's tools and the scorer both use
the mock; the result is labelled `generated`, never official:

```bash
agent/.venv/bin/python agent/builder/build.py briefs/brief-a.md <mock_url> --cases mock/practice-cases.json --name practice-a
```

```bash
agent/.venv/bin/python agent/builder/build.py briefs/brief-a.md briefs/brief-b.md <mock_url> --cases mock/practice-cases.json --name practice-b
```

Only the cases tagged for the brief being built run: 31 for Brief A and 22 for Brief B in the
53-case file. To score an agent that was already built against the mock, use the kit's runner:

```bash
FREYA_BANK_HOST=<mock_url> python3 tools/run_cases.py <agent_id> --cases mock/practice-cases.json --brief A
```

The mock follows the practice contract as the kit documents it. Where the organisers' bank behaves
differently in a detail, a case can pass here and fail there, or the other way round.

## How it answers

- `POST <any prefix>/<service>` with a JSON body. The service is the last part of the path, so
  `/verify_identity` and `/v1/verify_identity` are the same service.
- A refusal is `{"ok": false, "error": "..."}` with status 200. A fault a fixture asks for is
  status 500. An unknown service is 404.
- Like the real bank, the mock checks shapes and order, not the brief. It records a promise on a
  holiday without complaint. Keeping the brief is the agent's job.

## One call, one state

A workflow built with a mock address sends the platform's call id in the header `X-Call-Id`. Each
call then has its own Durable Object, so two calls for the same customer never share a wrong-answer
count or a promise, and a read always sees the write before it.

If the platform sends no call id, the state is the customer's: a call that begins after a closed
one starts afresh. The services a call may begin with are listed in `startsCall` in `bank.js`.

## See what the agent did

```bash
curl https://freya-bank-mock.<your-subdomain>.workers.dev/__ledger/<customer_id>
```

It returns every call for that customer with each request, each answer and the state at the end.
`POST /__reset/<customer_id>` forgets them.

## Rewriting `bank.js` for a case

A service is a function `(session, customer, body)` that returns the answer's JSON body.

- `session` is what this call has done so far. `newSession()` says how it starts.
- `customer` is this customer's entry in `customers.js`.
- `throw new Refused('why')` answers `{"ok": false, "error": "why"}`.
- `customerField` names the body field that carries the customer's id.

Keep the names of services and fields exactly as the service contract writes them: the builder
takes them from the same contract.
