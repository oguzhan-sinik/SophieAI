# TICKET-05 — Tiered model assignment for token and resource efficiency

The canonical ticket is [generalisation_agent/docs/tickets/ticket-05.md](../../../generalisation_agent/docs/tickets/ticket-05.md).

It routes every `ADKRoles.ask` call to a per-role model tier: `BUILDER_MODEL` (e.g. `openrouter/openai/gpt-6.1-sol`) for design/fix/interpretation, `openrouter/openai/gpt-6-luna-pro` for independent checks and grading, and `openrouter/deepseek/deepseek-v4.1-flash` for high-volume per-turn roles. This pointer keeps implementation requirements in one place.
