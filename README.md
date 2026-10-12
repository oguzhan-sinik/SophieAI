# Build the Builder: SophieAI

Our entry for the Freya "Build the Builder" hackathon (October 2026). It is a **builder**: a
program that reads a bank's documents and creates a phone agent on the Freya platform, tests that
agent with simulated callers, repairs what fails and exports the result. One command, no manual
edit of the agent.

Team: Burak Alican Kılınç and Oğuzhan Şinik.

The organisers' own starter-kit instructions are in [docs/kit-readme.md](docs/kit-readme.md).

## What the builder does

Given a brief (or a whole case folder) and the address of the bank's services:

1. **Reads the sources.** Markdown, text, Word, Excel, PDF, JSON and YAML. A large data file is
   shown by its first records only.
2. **Gets the service contract.** An OpenAPI file if there is one; otherwise one model call writes
   it from the bank's service document.
3. **Writes test callers.** The kit's practice customers where they exist. For a case without them,
   the builder writes callers from the example calls in the documents, plus up to eight of its own.
4. **Lists the rules.** For a large folder: in parts side by side, then compacted to one line per
   rule, the later document winning. Can be skipped with `--no-rule-list`.
5. **Designs the agent** as a compact workflow source (one model call).
6. **Compiles it.** Tools are expanded from the contract, code stages get the helpers they call,
   and the controller adds what designs kept getting wrong: date and amount conversion, loop guards,
   default routes.
7. **Checks it statically** and on Freya's dry run, with up to three repair calls.
8. **Tests it live** with the simulated callers, **repairs** it on their failures, keeps a fix only
   if nothing got worse, and repeats while the budget lasts.
9. **Exports** the best measured version and a trace of everything it did.

The phone agent itself runs on Freya's own model, which the builder never changes.

## Results

All numbers are from single runs on 11 October 2026. The same agent can pass a caller in one run
and fail it in the next, so read them as indications.

| What | Result | Tested with |
|---|---|---|
| Practice Brief A (one product) | 10 of 10, first design | the organisers' practice customers and bank |
| Practice Brief B (up to three products) | 3 of 3, first design | the organisers' practice customers and bank |
| Brief A, our own wider set | 27 of 31 after one repair round | 31 cases of our own on our mock; run stopped before export |
| Final case (credit card statement debt, Turkish) | 13 of 14 | callers the builder wrote: the case's 6 example scenarios and 8 of its own |
| Final case, each caller played twice | 11 of 14 passed both times; all 6 examples both times | a later run, freshly written callers |

Known weak spots of the submitted final agent: a caller who stays angry after three calming
replies is not handed over correctly, the week change on a joint statement is flaky, and silence
handling is untested because a chat simulation cannot stay silent.

## The final submission

- [submission.json](submission.json): team, commit, command, paths, mock address.
- [submission/final.workflow.json](submission/final.workflow.json): the exported agent.
- [traces/final.log](traces/final.log): the builder's trace.

The workflow came from two builder runs on the case folder: a design run, then a run that resumed
that design (`--resume-run`), tested it and repaired it. The trace holds both, each under its own
header line. No workflow was edited by hand.

## Run it

Python 3.10 or newer, from the repository root:

```bash
python3 -m venv agent/.venv
agent/.venv/bin/pip install -r agent/requirements.lock
cp env.example env.sh    # then put your keys in env.sh; it is git-ignored
```

Keys in `env.sh`: `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY` (any secret of 16 or more characters) and
a model provider key with the model tiers (`OPENROUTER_API_KEY`, `MODEL_TIER_HARD` and so on). The
builder names a missing key and stops before doing any work.

A practice brief (Brief B builds on Brief A, so both are given):

```bash
agent/.venv/bin/python agent/builder/build.py briefs/brief-a.md
agent/.venv/bin/python agent/builder/build.py briefs/brief-a.md briefs/brief-b.md
```

A case folder with your own mock of the bank:

```bash
agent/.venv/bin/python agent/builder/build.py <case_folder> <mock_url> 2>&1 | tee traces/final.log
```

The last line printed is a JSON result with the export path (`agent/out/<name>.workflow.json`), the
trace path and the score.

| Option | What it does |
|---|---|
| `--name` | Name of the build: the Freya slot and the export file |
| `--openapi` | Use this contract file instead of looking for one or writing one |
| `--cases` | Practice cases of your own, run against your mock |
| `--no-rule-list` | Skip the rule list; the designer reads the documents directly |
| `--resume-run <run folder>` | Reuse an earlier run's design instead of designing again |
| `--resume-best` | With `--resume-run`: start from that run's best measured version |

Limits come from the environment: `MAX_WALL_SECONDS` (default three hours),
`LLM_CALL_TIMEOUT_SECONDS` (default thirty minutes), `EVAL_MAX_SIMULATIONS` (test rounds, default 4)
and `EVAL_REPETITIONS` (plays per caller, default 1). `agent/.env.example` still shows the older,
lower limits of 1800 and 480 seconds; a large case folder needs more than those.

Every run leaves a folder under `agent/artifacts/` with its trace, each version of the design,
every model call and every test call.

## How callers are understood

Callers say numbers in two parts, correct themselves, tell stories, ask questions back, say
amounts and dates in words, and name one of several things their own way ("all three", "not the
car loan"). The agent's model is not trusted to get these right. Small helpers, compiled into the
agent, read the caller's own words in Turkish and English: dates, amounts, digits, a number
collected over several replies, and which of several things was meant. Details and the phrase
tables are in [agent/README.md](agent/README.md) and `agent/tests/test_speech.py`.

## Repository layout

| Path | What it is |
|---|---|
| `agent/builder/` | The builder: sources, contract compiler, runtime helpers, design rules, static checks, Freya adapter, the build loop |
| `agent/tests/` | Its tests |
| `agent/docs/tickets/` | Design notes, one ticket per piece of work; `ticket-06.md` covers caller speech and the final |
| `mock/` | A Cloudflare Worker that stands in for the bank: the practice services and the final case's seven statement services. See [mock/README.md](mock/README.md) |
| `submission/`, `traces/`, `submission.json` | The final submission |
| `observability/` | A read-only dashboard over a run's artifacts |
| `generalisation_agent/` | Earlier work on synthetic briefs and customers for testing the builder offline |
| `briefs/`, `tools/`, `docs/`, `examples/`, `freya.py`, `public-test-set.json` | The organisers' starter kit, unchanged |

## Tests

```bash
agent/.venv/bin/python -m pytest agent/tests observability/tests generalisation_agent/tests -q
```

568 pass and 6 are skipped (5 need Docker, 1 needs a saved practice design on the machine).

```bash
node mock/test.mjs
```

The final case's mock check needs the organisers' case folder, which is not in this repository:

```bash
node mock/test-statement.mjs "<case folder>/test-environment/test-customers.json"
```

## What is not done

- The final agent was built in two runs, not one fresh run of the submitted command.
- There is no independent held-out score for the final agent: it was repaired against the case's
  own examples and callers the builder wrote.
- The build with the compact rule list scored 0 of 6 on its first test and was stopped for time, so
  the rule list's value on the final case is unmeasured.
- The deployed mock is not the version in `mock/`. It returned 622 of 623 listed answers exactly;
  the difference is one error case the agent never triggers.
- Ideas not built: letting the compiler own "read back, clear yes, write once" for any write and
  exact speech for prepared text, and replaying only the failed callers in a repair round.
