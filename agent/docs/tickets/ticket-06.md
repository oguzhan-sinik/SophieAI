# Ticket 06 — The caller speaks like a person, in Turkish

Status: the final case is submitted, 11 October 2026, 19:30 UTC; section 12 lists what was done and what is open. First written
14:40 UTC; rewritten 15:00 UTC around what the organisers said about how callers talk.

Sources: the official page as it reads today (`freyavoice.ai/hackathon`, tabs Overview, Evaluation,
Submit, FAQ), the kit, and this project's own runs.

## 1. What the final is (read today, differs from kit README v3)

- One case, in **Turkish**: Freya Bank's credit card statement-debt line. "A different call from
  the practice."
- Input is a **zip of the bank's documents** in Markdown, Word, PDF and Excel: analysis, flow
  drawing, announcements, service contract, test customers, questions and answers, six example
  conversations. `BRIEF.md` first; `README.md` says what each file is.
- The team writes a **mock of the bank's services on Cloudflare Workers**, from the service
  contract and the test customers. The agent's tools call that mock during the hidden test. If it
  is wrong or down, those conversations fail.
- Run command shape: `build.py {case_folder} {mock_url}`. Submit one workflow, its trace and
  `submission.json` before 20:00 UTC.
- Hidden simulated customers; the criteria and the weights are not published. "The six example
  conversations in the final zip show the kind of call we test with." The workflow is reviewed too.
- Allowed after 17:00: fixing a bug, including a crash on an unexpected file type. Not allowed:
  writing anything from the case into the builder.

## 2. How callers talk (what we were told)

> Final customers talk like people: a number said in two parts ("463..." then "51"), corrections,
> talk about other things, a question back, amounts and dates in words.

These five are the spine of this ticket. Each one is handled in three places, so that no single
model call has to get it right:

1. **A helper** in the runtime reads the caller's words, in Turkish and in English.
2. **The extraction text** the controller writes says what belongs in a value and what does not.
3. **A design rule** says what the stage does with the result.

| # | What we were told | How it sounds | What must hold | Where it is enforced |
|---|---|---|---|---|
| H1 | A number in two parts | "463" … "51"; "dört yüz altmış üç" … "elli bir"; "kırk dört" … "yetmiş bir"; "on dört Mart" … "bin dokuz yüz seksen sekiz" | The first part is kept. Only the rest is asked for. The parts are joined in order, zeros kept. Nothing partial reaches a tool. No digit and no year is ever filled in | `ctl_collect` joins digit parts against the expected length; `ctl_digits` reads digits said one by one, in groups or as numerals; `ctl_identity_date` returns a date only when day, month and year are all there |
| H2 | Corrections | "yirmi bir, pardon, yirmi"; "the 21st, sorry, I mean the 20th"; "evet ama cumaya" after a read-back | The corrected value wins. A correction after a read-back voids the earlier yes: new read-back, new yes | Every helper reads what follows the last correction word first; `ctl_proposal` gives each changed tuple a new revision; the read-back rule |
| H3 | Talk about other things | "geçen hafta on yedi lira kırk kuruş ödedim"; "kuzenimin düğünü ayın otuzunda" | A number or a day in a story is not a proposal. The pending question is asked again | Controller-written extraction text for days and amounts ("only the value the caller proposes here"); `ctl_amount` takes the number that carries the currency; the resume rule |
| H4 | A question back | "bunu neden soruyorsunuz?"; "hangi hesap için?"; "robot musunuz?" | One safe line of answer, then the same question again. It is no answer, no refusal and no consent, and it costs no attempt | Reply categories with their own value for a question; `ctl_collect` leaves the kept part untouched when a reply holds no digits |
| H6 | One of several things (seen live on Brief B, not in what we were told) | "I can pay all three this Friday"; "the credit card tomorrow, but not the personal loan or the car loan"; "üçünü de öderim"; "taşıt kredisi hariç hepsi" | Every thing the reply names gets the reply's day and amount. What it declines is not lost and not asked as if nothing was said. "Which one?" only when one mention fits two things | `ctl_choice` gives chosen, declined and unclear positions; a static check rejects code that compares the caller's words with fixed text; design rule 6 |
| H5 | Amounts and dates in words | "bin iki yüz elli lira elli kuruş"; "1.250,50 TL"; "ayın yirmi altısında"; "haftaya salı"; "four hundred and fifty-five" | The same value as in digits, to the cent and to the day, against the call's `now` | `ctl_amount`, `ctl_date`; extraction types `amount` and `date` are captured as the caller's words and converted in code, never by the extraction model |

More behaviours, seen in the kit's styles, the stress personas and live failures:

| # | Behaviour | Example | What the agent must do | Seen failing |
|---|---|---|---|---|
| S6 | A hold | "bir saniye", "bir dakika bakayım" | Wait; it is no answer, no refusal, no consent; ask once more after it | Not covered by any rule |
| S8 | Refusal and question together | "istemiyorum. indirim olur mu?" | The refusal decides; answer the question, do not repeat the offer | 14:22 (offer made twice) |
| S10 | Acknowledgement that is not consent | "tamam", "anladım", "hı hı" at a read-back | Not a yes to a write; ask for an explicit yes once | Passed |
| S11 | Acceptance that restates the values | "beş yüz kırk lirayı kabul ediyorum, yirmi yedisinde" | A yes when the values match the offer | 14:30 (read as ambiguous amount) |
| S12 | A reply cut off mid-sentence | "kabul ediyorum, ayın" | Use what is complete; ask for the missing part only | 14:30 |
| S13 | A reply with no route | Plain "tamam" after the last line | A stage that needs no answer does not wait for one | 14:30 (goodbye loop, 16 turns) |
| S14 | A period, not a day | "ay sonu", "maaş gününde", "gelecek hafta" | Not a day: ask for the day | English only |
| S15 | Someone else answers | "ben eşiyim" | Nothing about the debt; the source's third-party path | Passed |
| S16 | A claim the agent must not echo | "kaydettiniz değil mi?" | Never state a result the tool has not returned | 14:30 ("I have scheduled the payment") |

## 3. Blocking gaps (each one alone fails the final)

| # | Gap | Evidence | Needed |
|---|---|---|---|
| B1 | Speech helpers are English only | `ctl_date` returns `''` for yarın, bu cuma, ayın yirmi altısı, 26 Ekim 2026; `ctl_identity_date` for 14 Mart 1988 and 14.03.1988; `ctl_digits` for dört dört yedi bir and for any number said in groups | Section 4 |
| B2 | The builder takes brief files and an OpenAPI file | The final gives a folder and a mock URL | Section 7 |
| B3 | No mock, no Cloudflare tooling | `wrangler` is not installed here | Section 8 |
| B4 | Prompts and examples are English | The design rules quote English lines | Section 6 |
| B5 | The compiled agent is at the size of a megabyte | The 66-stage agent is 964,766 bytes as a request; 765 KB of it is the helper prelude, copied into each of 41 code stages. More helpers in every stage would pass 1 MiB, a common request limit | Section 5 |
| B6 | The tool contract may not be an OpenAPI file | The zip names a "service contract" among Word, PDF and Excel documents | Section 7 |
| B7 | `tee` would capture one line | The builder prints one JSON line; the trace is a file under `agent/artifacts/` | Section 7 |

## 4. The helpers (B1, H1–H5)

General Turkish and English only; nothing here comes from a case. All take the caller's words and
return text; `''` always means "not there", never a guess.

| Helper | Reads | Returns |
|---|---|---|
| `ctl_date(said, call_now, next_weekday)` | bugün, yarın, öbür gün, yarından sonra; bu / gelecek / haftaya + weekday; "N gün sonra", "N hafta sonra"; "ayın N'i", "N'inde", "yirmi altısında"; "6 Kasım", "Kasımın altısı"; 26.10, 26.10.2026; all the English forms as before, and "Tuesday next week" | `YYYY-MM-DD`, or `''` for a period ("ay sonu", "gelecek hafta") |
| `ctl_identity_date(said)` | "on dört Mart bin dokuz yüz seksen sekiz", "14 Mart 1988", 14.03.1988, the English forms | The date only when day, month and year are said; the last complete one when two are in the words |
| `ctl_digits(said, count)` | Digits one by one ("dört dört yedi bir"), in groups ("kırk dört yetmiş bir", "four sixty-three", "dört yüz altmış üç"), numerals ("463"), zeros ("sıfır beş"), "double" / "çift" | The digits in order. `''` when another word is among them, so a question or a hold is never sent as an answer |
| `ctl_collect(vars, name, said, count)` | One reply towards a number of `count` digits | The whole number once `count` digits are there, else `''`. Keeps the parts in `<name>_parts`, sets `<name>_complete` and `<name>_heard`. A whole number or a correction replaces the kept part |
| `ctl_amount(said)` | "bin iki yüz elli lira elli kuruş", "yüz elli buçuk lira", "1.250,50 TL", "1,250.50", "four hundred and fifty-five dollars and fifty cents" | `1250.50` as text. `''` for a reference ("tamamı", "the minimum"), for two amounts, and for a split that can be read two ways ("twelve fifty") |

Rules inside the helpers:

- Letters are folded (ı→i, ş→s, ğ→g, ü→u, ö→o, ç→c, İ→i), so a transcript without Turkish letters
  reads the same. Suffixes and apostrophes are stripped: "26'sında", "kasımın", "cumaya".
- What follows the last correction word (pardon, yani, hayır, yok, düzeltiyorum; sorry, I mean,
  actually, no wait) is read first; the whole reply only if that part holds no value.
- "on" and "bin" are numbers only in a Turkish reply, so "540 on Friday" stays 540.
- "bir" alone and "onu", "ona", "biri" are everyday words: alone they are no amount and no day.
- A time of day is not a day of the month: "on birde" and "11'de" are at eleven, "on birinde" and
  "11'inde" are on the eleventh. With a dot, "10.30" is a time and "5.10 dollars" an amount.
- Dates given only as numbers are day, then month: "14.03.1988", "14 3 1988", "on dört üç bin dokuz
  yüz seksen sekiz".
- For a date of birth the month that was said is the month of the answer. A day that stands apart
  from its month gives `''`, never another month: a wrong date sent as an answer costs an attempt.
- English keeps working; every existing test stays green.

## 5. Where the helpers are compiled in (B5)

- A code stage gets only the helpers it calls, with what those call.
- Days and amounts are converted in the first code stage after a stage that extracts one, and in
  the hook of a tool they are bound to. Later code stages find them converted already.
- Extraction type `amount` joins `date` as a controller-owned type: captured as the caller's words,
  with controller-written text on what counts, converted before any code runs, `<name>_said`
  keeping the words.

## 6. Rules for the designer (B4, H1–H5, S6–S16)

Already in the rules: fragments and slots, explicit year, corrections void consent, unrelated
numbers ignored, the specific reading wins, the reserved word.

Added:

- **Language.** The agent speaks the language of the source documents. Every example in the rules
  is an illustration, never text to copy. Names, codes and enum values are never translated.
- **The five behaviours by name**, each with what the stage does (section 2).
- A hold is none of answer, refusal or consent: wait, then ask the pending question once (S6).
- An acceptance that repeats the offered values is an acceptance (S11).
- A cut-off reply: use what is complete, ask for the missing part only (S12).
- A stage that needs no answer does not wait for one; every reply category a stage can extract
  leaves it or is asked again on purpose (S13). This stays a hint in the static checks: made an
  error, the only cheap fix is a route to the stage itself, which re-enters it and repeats its
  fixed opening line.
- A result is stated only from a variable the tool's stage set; the system prompt says so in the
  language of the call, also for when the caller asks or assumes it (S16).
- Documents that list test customers or example conversations show data and style. Nothing about
  one customer goes into the workflow.

## 7. Input, contract and trace (B2, B6, B7)

- `python3 agent/builder/build.py <case_folder> <mock_url>`. A folder is read whole, `BRIEF.md`
  first, then `README.md`, then the rest by name.
- Read: Markdown, text, CSV, JSON, YAML, HTML, XML and SVG as text; Word and Excel from their own
  XML; PDF with `pypdf` when it is installed, else a plain reader. Anything else (an image, an old
  binary format) is skipped with a line in the trace, never a crash.
- An OpenAPI file in the folder (JSON or YAML) is the tool contract. With none, one model call
  writes the contract from the documents, operation for operation, nothing invented.
- With a mock URL every tool URL carries the mock's host, the contract's own server and security
  are ignored, and each tool call sends the platform's call id in a header so the mock can keep
  calls apart.
- The build is named after the folder: Freya slot `builder-<folder>`, export
  `agent/out/<folder>.workflow.json`.
- The trace is echoed to stderr line by line, so `2>&1 | tee traces/final.log` holds all of it.

## 8. The mock (B3)

`mock/`: a Cloudflare Worker with one Durable Object per call, so two calls never share state and
a read sees the write before it. `bank.js` holds the bank's behaviour, one function per service;
`customers.json` holds the fixtures. Shipped with the practice contract and the practice
customers as the working example; at 17:00 both files are rewritten from the service contract and
the test customers. `node mock/test.mjs` runs it without Cloudflare. Deploying needs the team's
account: `npx wrangler login`, `npx wrangler deploy`.

## 9. Order of work

| Order | Work | How it is checked |
|---|---|---|
| 1 | Helpers: Turkish, groups, corrections, amounts, `ctl_collect` (section 4) | `agent/tests/test_speech.py`: a table of phrases with expected values, Turkish and English |
| 2 | Helpers compiled where they are needed (section 5) | The compiled practice design is smaller than before and its code still runs |
| 3 | Language rule and the speech rules (section 6) | One design-only build still passes the static checks |
| 4 | Folder input, mock URL, file types, contract from documents, trace (section 7) | `agent/tests/test_inputs.py`: a folder with `.md`, `.docx`, `.xlsx`, `.pdf`, `.png` builds without a crash; tool URLs carry the mock host |
| 5 | Mock Worker (section 8) | `node mock/test.mjs`; deployed once with the practice contract |

## 10. Acceptance

- Every phrase in the test tables resolves to the expected value, in Turkish and English.
- "463" then "51" becomes 46351 with one question for the rest; a question between the two parts
  loses nothing; "pardon" replaces what was said before it.
- `build.py <folder> <mock_url>` runs on a folder of mixed file types and exports an agent whose
  tools call the mock.
- On Brief A (English) the build still scores as before; nothing here may cost the practice score.
- After 17:00: the six example conversations are read by the builder as source documents; nothing
  from them is written into the builder.

## 11. Not in this ticket

- Turkish stress personas on Freya (the kit's styles are English).
- A test loop on the final case: the builder exports after the static checks, as for any brief
  without practice customers. With the mock in the team's hands a simulation against it is
  possible, but nothing wires it.
- The identity and closing checks look for the practice tool names. With other names they check
  nothing; the build still runs.
- Tool contracts with path or query parameters stop the build with a named error.
- Times of day in words ("öğleden sonra üçte").

## 12. Status (11 October 2026, 19:35 UTC)

Built and checked here:

| Work | Where | Check |
|---|---|---|
| Helpers: Turkish, groups, corrections, amounts, `ctl_collect` | `agent/builder/runtime.py` | `agent/tests/test_speech.py`, 218 tests; the 292 tests from before still pass |
| Helpers compiled where they are needed | `runtime.py`: `helpers_for`, `apply` | The saved 10 of 10 design recompiles to 628 KB (was 965 KB), passes the static checks, and all 41 of its code stages run |
| Language rule, the five behaviours, S6 to S16 | `agent/builder/prompts.py` | The live test below |
| Folder input, mock address, file types, contract from documents, trace to stderr | `agent/builder/sources.py`, `contracts.py`, `build.py` | `agent/tests/test_inputs.py` |
| Mock Worker | `mock/` | `node mock/test.mjs` |
| A model call refused for its size is tried again at the size the key can pay for | `agent/builder/adk.py` | `agent/tests/test_core.py` |

Live test, 15:57 to 16:13 UTC, Brief A with the ten practice customers, run `20261011T165735_8316cc5c`:

- **10 of 10 on the first design**, no fix round needed, 926 seconds in all. The design was written
  under the new rules: 70 stages, 5 values of type `amount`, 6 of type `date`, `ctl_collect` for the
  phone digits, `ctl_amount`, and the sentence about never stating an unconfirmed result in its
  system prompt. The compiled agent is 793 KB as a request.
- The key's limit was raised from 10 to 35 dollars first; at 10 a build was refused before any model ran.
- The rule extraction failed its own checks twice (a reference to a rule that does not exist, a rule
  without an obligation) and cost 6.5 minutes; the designer then read the brief alone, as designed.
- One static error stayed through three fix calls, so the export is marked best effort: a stage
  that answers a request for a person and returns the caller to where the call was can be entered
  before identity. Two things were wrong on our side and are fixed: the error showed only the end
  of the route, so the fix calls edited the wrong stage; and the check had no way to accept such a
  stage. It now shows where the route starts, and accepts a transition that tests the result the
  identity stages map from the tool's response. The rules say the same. The edit the message asks
  for clears the error on that design (checked without a model).

Second live test, 16:18 to 16:36 UTC, Briefs A and B with the three Brief B practice customers, run
`20261011T171814_232e0066`:

- **1 of 3**, on the first design and after two measured fix rounds; a third fix was wording only
  and is exported unmeasured. There is no earlier Brief B run on this machine to compare with.
- PUB-11: the caller's date of birth was recognised as an answer, but the platform's extraction
  dropped the words themselves; asked again, the agent's model made up a question ("the name of
  your first pet") and the call closed as declined. The fix loop repaired the identity stage. The
  rules now say: a value that holds the caller's own words gets a low `min_confidence`, and a stage
  that asks again names the thing asked for in full.
- PUB-11 after that fix, and PUB-12: the multi-product negotiation of this design ends with three
  `refused` notes and no promise, also when the caller agrees. A fault in the design's logic, not in
  how the caller was understood. PUB-13 passed.
- The design's one static error was a tool hook that called a helper. Hooks now carry the helpers
  they call, as code stages do.

Practice cases of the team's own (`public-plus-adversarial-53.json`: the kit's 13, 30 adversarial, 10
with Turkish-speaking callers):

- The organisers' bank answers "unknown practice case" for them, and the file has no security
  answers. `mock/make_fixtures.py` writes fixtures and `mock/practice-cases.json`; the mock serves the
  kit runner's session and ledger routes; `build.py ... <mock_url> --cases mock/practice-cases.json`
  runs the cases tagged for the brief (31 for A, 22 for B) against the mock, labelled `generated`.
- The mock is deployed at `https://freya-bank-mock.ogzdlk06.workers.dev` (17:15 UTC). `mock/smoke.py` passes
  25 of 25 checks against it: a whole call, two calls at once kept apart by the call id, a service
  fault, and session, identity and account for all 53 customers. The slowest service call took 1.1 s.

After that run, 16:45 to 16:57 UTC. The transcripts of PUB-11 and PUB-12 showed one cause behind both
failures: the design's own code compared the caller's words with fixed strings. "All three" was not in
its list and "the credit card" was not "credit card", so both replies went to a "which product?"
stage. There the agent's model improvised (asked for an amount, said "I have recorded your promise"
with nothing written, said goodbye about twenty times) until the loop guard left through the refusal
route and three `refused` notes were written. Changed:

- `ctl_choice(said, names)`: which of several known things a reply names, in English and Turkish,
  with what was declined in the same reply and what is unclear (H6 in section 2).
- A static check: code that compares a free-words extraction variable with fixed text is an error.
  It flags exactly the two comparisons of that design and nothing in the 10 of 10 Brief A design.
- Design rules: item 6 of HUMAN SPEECH; a yes at the read-back that repeats a stated value is the
  confirmation; the stage after an agreement that is written later gives the agent a true
  acknowledgement.

Third live test, 16:57 to 17:09 UTC, Briefs A and B again, run `20261011T175718_1bb1aae6`:

- **3 of 3 on the first design**, in 11.5 minutes with one simulation. The design calls `ctl_choice`
  in two code stages (choosing products from a reply, reading the confirmation). Its only static
  errors were four stages without a default route, repaired by one fix call.
- PUB-11 wrote three promises, PUB-12 one promise and two `refused` notes, PUB-13 two promises.
- One rule was added after this build started and has not been in a build: the agent never says
  goodbye outside a closing stage.

The final case, 17:45 to 19:30 UTC (Freya Bank, credit card statement debt; folder with eighteen files,
seven lookup services, calls in Turkish, no practice customers):

- **Submitted:** `submission/final.workflow.json`, `traces/final.log`, `submission.json`; builder code
  `550ffd5`, mock `https://freya-bank-mock.ogzdlk06.workers.dev`. The builder's own test passed 13 of 14
  simulated callers (the six example scenarios of the case and seven of eight it wrote itself); six
  callers written by hand from the examples passed 6 of 6. The one failure, a caller who stays silent,
  cannot be played by a chat simulation.
- **What the case broke in the builder, each fixed in general terms:** service names with dots; request
  and answer fields inside objects; an object in an answer never reached code (every balance read as
  missing); a 707 KB data file sent whole; a designer that withheld the workflow because the bank has no
  closing service; consent helpers that accepted only an amount on a day (no week change, no e-mail);
  repairs that could not reach interrupt stages; a rule list that timed out, then lost every rule of the
  main documents to a completeness check meant for whole lists.
- **What was added, beyond a bug fix:** test callers written from a case's example calls plus up to
  eight from its documents, and the repair loop on them; the rule list in parts with a one-line digest
  (569 rules listed, 131 kept, 34,000 characters); `--no-rule-list`; `--resume-best`.
- **Platform facts from a probe call:** a nested request template is sent as written; after an HTTP
  404 or 500 no answer field is mapped and no hook runs, and `<stage>_status_code` holds the status.
- **Mock:** the pushed Worker serves the seven services from the bank's own answers (1,041 lookups
  exact locally). The deployed one is another version: 622 of 623 listed answers exact, an empty
  `intAddressInfoType` answers 200 where the contract says 400.
- **Not done:** the submitted workflow came from two runs (a design, then a resumed run that repaired
  it), not one fresh run of the submitted command; no independent held-out score; the build with the
  compact rule list scored 0 of 6 on its first test and was stopped for time.

Open:

1. **No design has been written since the last rule changes above**, and none in Turkish or from a folder.
2. **The practice run was plain speech.** The five behaviours are covered by the helper tests, not by
   a simulation with the kit's styles (`--style pieces`, `corrects`, `talkative`, `asks_back`, `in_words`).
3. **The mock is not deployed.** It needs the team's Cloudflare account (`mock/README.md`).
4. **No call has carried the call-id header yet.** `X-Call-Id: {{call.call_id}}` is sent only with a
   mock address. Freya's dry run accepts the saved 10 of 10 design recompiled with it (15:55 UTC,
   628 KB). Whether the platform fills the value in shows in the first call against the mock; the
   mock ignores a value that was not filled in.
5. **PDF.** `pypdf` is not installed here; the plain reader manages simple PDFs only.
6. **The Docker tests** (5, skipped by default) were not run: Docker is not running on this machine.
7. `agent/docs/tickets/attachments/ticket-06-turkish-helpers.patch` is the earlier draft of
   section 4; `runtime.py` now holds its content and the patch no longer applies.
