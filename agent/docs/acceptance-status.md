# Ticket 1 acceptance evidence

This is an evidence ledger, not a completion claim. Forty-six local tests currently pass. Fake controller/API tests demonstrate implementation behavior only; they do not establish actual bank-policy correctness.

| Acceptance checks | Evidence available | Still required |
|---|---|---|
| AT-01–03, AT-18: unfamiliar input, changed rules, inheritance | Live source-backed extraction for Brief A and changed fixture; actual conflicting fixture rejected; local changed-schema and precedence tests | Successful generated deployment/export for unfamiliar and inherited briefs |
| AT-04, AT-19, AT-21–24: workflow safety and shape | Local adversarial validation tests; unfamiliar proposal passed static and reviewed code checks; real dry-run detected undocumented runtime rejection of `loop_prompt` | Successful repaired live deployment |
| AT-05–09: lineage, group advantages, strict scores | Immutable archive, mutation and scoring tests, including incomplete and mismatched suites | Actual evaluated sibling branches and selection |
| AT-10–12: feedback modes and comparison | Sentinel isolation plus both-mode controller integration from identical pinned root | Real paired experiment and performance report |
| AT-13: serialization | Separate-process lock test; persisted simulation lease | Multiple real benchmark requests completing serially |
| AT-14: recovery | Controller failure and cached actual-export fallback tests | Actual generated champion restore/export under deadline |
| AT-15–16: telemetry and redaction | Local outage and secret-redaction tests, durable live traces | Remote LangSmith receipt; requires configured credentials |
| AT-17, AT-32: submission and trace | Real stock workflow export/startup trace; generated-run source/model artifacts | Generated champion submission and complete real run trace |
| AT-20: publishing | Real stock deployment/publish/export; fake stale-version rejection | Generated candidate's benchmark run version verified |
| AT-25–29: Brief A/B policy | Briefs read, source compilation and deterministic validation implemented | Actual policy suites, including inherited multi-product/transfer behavior |
| AT-30: naturalism | Styles supported by original runner adapter; held-out repetition path implemented | Actual speaking-style runs |
| AT-31: audit | Supplied kit/documents read and signatures/hashes recorded in kit audit | No outstanding source inventory work |

The P0 definition of done remains open until live generation, evaluation, evolution, paired comparison, recovery and remote tracing have the required evidence.
