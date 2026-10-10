"""Atomic immutable artifacts and durable local tracing with optional LangSmith."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .config import writable


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def write_json(path, value, immutable=False):
    path = writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n"
    if immutable:
        with path.open("x") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temp.open("w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)


class Redactor:
    def __init__(self):
        self.secrets = [v for k, v in os.environ.items() if any(x in k.upper() for x in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "TEAM_KEY", "MODAL_KEY")) and len(v) >= 6]

    def __call__(self, value):
        if isinstance(value, dict):
            return {k: "[REDACTED]" if re.search(r"^(authorization|x-team-key|api_key|password|date_of_birth|phone_last4|phone|email|customer_id)$", k, re.I) else self(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"\b(?:fak_|nvapi-|sk-)[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
            value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
        return value

    def assert_no_secrets(self, value):
        text = encoded(value)
        if any(secret in text for secret in self.secrets):
            raise ValueError("Credential found in artifact; refusing to persist")


class Trace:
    def __init__(self, path, metadata, remote=True):
        self.path = writable(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.redact = Redactor()
        self.metadata = metadata
        self.remote = None
        self.stack = []
        if remote and os.getenv("LANGSMITH_API_KEY"):
            try:
                from langsmith import Client, RunTree
                client = Client(timeout_ms=2000)
                self.remote = RunTree(name="FreyaBuilderRun", run_type="chain", inputs=self.redact(metadata), project_name=os.getenv("LANGSMITH_PROJECT", "freya-builder-optimizer"), client=client)
                self.remote.post()
            except Exception as exc:
                self.event("telemetry_unavailable", error=type(exc).__name__)
        self.event("run_start", **metadata, langsmith_enabled=self.remote is not None)

    def event(self, kind, **values):
        record = self.redact({"at": now(), "event": kind, **self.metadata, **values})
        with self.path.open("a") as stream:
            stream.write(encoded(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @contextmanager
    def span(self, name, **values):
        self.event(name + "_start", **values)
        span = None
        try:
            parent = self.stack[-1] if self.stack else self.remote
            if parent:
                span = parent.create_child(name=name, run_type="llm" if "model" in values else "chain", inputs=self.redact(values))
                span.post()
                self.stack.append(span)
        except Exception:
            span = None
        try:
            yield
        except BaseException as exc:
            self.event(name + "_error", error=type(exc).__name__, message=str(exc))
            raise
        finally:
            self.event(name + "_end")
            if span:
                self.stack.pop()
                try:
                    span.end(outputs={"local_trace": str(self.path)})
                    span.patch()
                except Exception:
                    self.event("telemetry_unavailable", span=name)

    def close(self, **values):
        self.event("run_end", **values)
        if self.remote:
            try:
                self.remote.end(outputs=self.redact(values))
                self.remote.patch()
            except Exception:
                self.event("telemetry_unavailable", span="root")


class Archive:
    def __init__(self, root):
        self.root = writable(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "lineage.sqlite")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, parent TEXT REFERENCES candidates(id), hash TEXT NOT NULL, generation INTEGER, metadata TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.commit()

    def event(self, kind, **values):
        record = {"at": now(), "event": kind, **values}
        with self.db:
            self.db.execute("INSERT INTO events(payload) VALUES (?)", (encoded(record),))
        # SQLite is canonical; JSONL can be reconstructed after a crash between writes.
        with (self.root / "lineage.jsonl").open("a") as stream:
            stream.write(encoded(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def add(self, spec, parent=None, mutation=None, group=None, **metadata):
        workflow = spec["workflow"]
        Redactor().assert_no_secrets(spec)
        if parent and not self.db.execute("SELECT 1 FROM candidates WHERE id=?", (parent,)).fetchone():
            raise ValueError("Unknown parent")
        candidate_id = "cand_" + uuid.uuid4().hex[:12]
        generation = self.get(parent)["generation"] + 1 if parent else 0
        folder = self.root / "candidates" / candidate_id
        write_json(folder / "workflow.json", workflow, immutable=True)
        write_json(folder / "proposal.json", spec, immutable=True)
        if mutation:
            write_json(folder / "mutation.json", mutation, immutable=True)
        duplicate = self.db.execute("SELECT id FROM candidates WHERE hash=? LIMIT 1", (digest(workflow),)).fetchone()
        record = {"candidate_id": candidate_id, "parent_id": parent, "generation": generation, "sibling_group_id": group, "workflow_sha256": digest(workflow), "workflow_snapshot_path": str(folder / "workflow.json"), "created_at": now(), "duplicate_of": duplicate[0] if duplicate else None, **metadata}
        with self.db:
            self.db.execute("INSERT INTO candidates VALUES (?,?,?,?,?)", (candidate_id, parent, digest(workflow), generation, encoded(record)))
        self.event("candidate_created", **record)
        return record

    def get(self, candidate_id):
        row = self.db.execute("SELECT metadata FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError("Unknown candidate " + candidate_id)
        return json.loads(row[0])

    def spec(self, candidate_id):
        record = self.get(candidate_id)
        spec = json.loads((Path(record["workflow_snapshot_path"]).parent / "proposal.json").read_text())
        snapshot = json.loads(Path(record["workflow_snapshot_path"]).read_text())
        if digest(spec["workflow"]) != record["workflow_sha256"] or digest(snapshot) != record["workflow_sha256"]:
            raise ValueError("Immutable workflow snapshot was modified")
        return spec

    def checkpoint(self, **pointers):
        write_json(self.root / "champion.json", pointers)
        self.event("checkpoint", **pointers)
