"""Semantic diff between two Freya workflow snapshots (parent vs child).

Reports precise JSON-pointer-ish paths with before/after values. Never invents
changes: if a snapshot is missing, callers show a missing-artifact state.
"""
from __future__ import annotations

import json
from typing import Any

# Workflow sections compared semantically; everything else falls through to a
# generic recursive dict/list walk.
_SEMANTIC_KEYS = ("initial_node", "system_prompt", "task_message", "nodes", "global_nodes", "test_variables")

NodeChange = dict  # {"path", "op", "before", "after"}


def _diff(a: Any, b: Any, path: str, out: list[NodeChange], max_depth: int = 12) -> None:
    if a == b:
        return
    if max_depth <= 0 or not isinstance(a, type(b)) or not isinstance(a, (dict, list)):
        out.append({"path": path or "/", "op": "changed", "before": _short(a), "after": _short(b)})
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            ka, kb = a.get(k, _MISSING), b.get(k, _MISSING)
            kp = f"{path}/{k}"
            if ka is _MISSING:
                out.append({"path": kp, "op": "added", "before": None, "after": _short(kb)})
            elif kb is _MISSING:
                out.append({"path": kp, "op": "removed", "before": _short(ka), "after": None})
            else:
                _diff(ka, kb, kp, out, max_depth - 1)
    else:  # list
        if len(a) != len(b):
            out.append({"path": f"{path}[len]", "op": "changed",
                        "before": len(a), "after": len(b)})
        for i in range(max(len(a), len(b))):
            va = a[i] if i < len(a) else _MISSING
            vb = b[i] if i < len(b) else _MISSING
            if va is _MISSING:
                out.append({"path": f"{path}[{i}]", "op": "added", "before": None, "after": _short(vb)})
            elif vb is _MISSING:
                out.append({"path": f"{path}[{i}]", "op": "removed", "before": _short(va), "after": None})
            else:
                _diff(va, vb, f"{path}[{i}]", out, max_depth - 1)


class _Missing:
    def __repr__(self):  # pragma: no cover
        return "<missing>"


_MISSING = _Missing()


def _short(v: Any) -> Any:
    """Truncate long leaves (prompts, code) but keep them truthful."""
    if isinstance(v, str) and len(v) > 400:
        return v[:400] + f"... [truncated, {len(v)} chars]"
    return v


def summarize(changes: list[NodeChange]) -> dict:
    """Graph summary like: +2 nodes / -1 transition / 3 prompt changes (computed)."""
    s = {"nodes_added": 0, "nodes_removed": 0, "transitions_changed": 0, "prompt_changes": 0, "other": 0}
    for c in changes:
        p = c["path"]
        if p.startswith("/nodes/") and p.count("/") == 2:
            s["nodes_added" if c["op"] == "added" else "nodes_removed"] += 1
        elif "/transitions" in p:
            s["transitions_changed"] += 1
        elif any(k in p for k in ("task_message", "system_prompt", "description")):
            s["prompt_changes"] += 1
        else:
            s["other"] += 1
    return s


def diff_workflows(parent: dict, child: dict) -> dict:
    """Full semantic + raw diff of two workflow dicts."""
    changes: list[NodeChange] = []
    _diff(parent, child, "", changes)
    # node-level names for the UI
    changed_nodes = sorted({c["path"].split("/")[2] for c in changes
                            if c["path"].startswith("/nodes/") and c["path"].count("/") >= 3})
    return {
        "changes": changes,
        "summary": summarize(changes),
        "changed_nodes": changed_nodes,
        "identical": not changes,
    }


def diff_from_files(parent_bytes: bytes, child_bytes: bytes) -> dict:
    try:
        parent = json.loads(parent_bytes)
    except ValueError:
        return {"error": "parent snapshot unreadable"}
    try:
        child = json.loads(child_bytes)
    except ValueError:
        return {"error": "child snapshot unreadable"}
    return diff_workflows(parent, child)
