"""Freya Builder Studio — read-only observability over builder artifacts.

Ticket-03 implementation. Lives outside agent/ on purpose: it never writes to
or imports builder code; it only reads agent/artifacts/<run_id>/ JSON+JSONL.
"""
