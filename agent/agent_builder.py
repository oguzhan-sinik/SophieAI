"""Compatibility CLI: python3 agent/agent_builder.py brief.md [overlay.md]."""
import sys
sys.dont_write_bytecode = True
from builder.build import main

if __name__ == '__main__':
    raise SystemExit(main())
