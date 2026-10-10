"""Read-only HTTP + SSE server over the artifact store. Stdlib only."""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import diff as diffmod
from . import store as storemod
from .store import ArtifactForbidden, ArtifactMissing, RunNotFound, Store

STATIC_DIR = Path(__file__).parent / "static"
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 1.0


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, indent=1, default=str).encode("utf-8")


class Studio:
    def __init__(self, artifacts_dir: str) -> None:
        self.store = Store(artifacts_dir)

    # route handlers return (status, body_bytes, content_type)
    def handle(self, method: str, path: str, query: dict) -> tuple[int, bytes, str]:
        parts = [p for p in path.split("/") if p]
        if method == "GET" and path == "/api/health":
            return 200, _json_bytes({"ok": True, "artifacts_dir": str(self.store.root),
                                     "runs": len(self.store.run_ids())}), "application/json"
        if method == "GET" and parts[:2] == ["api", "runs"] and len(parts) == 2:
            runs = self.store.list_runs()
            status = query.get("status", [None])[0]
            if status:
                runs = [r for r in runs if r["status"] == status]
            return 200, _json_bytes({"items": runs, "count": len(runs)}), "application/json"
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "runs":
            run_id = parts[2]
            sub = parts[3:]
            try:
                return self._run_route(method, run_id, sub, query)
            except RunNotFound:
                return 404, _json_bytes({"error": "RUN_NOT_FOUND", "run_id": run_id}), "application/json"
            except ArtifactMissing as e:
                return 404, _json_bytes({"error": "ARTIFACT_MISSING", "detail": str(e)}), "application/json"
            except ArtifactForbidden as e:
                return 403, _json_bytes({"error": "ARTIFACT_RESTRICTED", "detail": str(e)}), "application/json"
        if method == "GET" and path in ("/", "/index.html"):
            return 200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8"
        return 404, _json_bytes({"error": "NOT_FOUND", "path": path}), "application/json"

    def _run_route(self, method, run_id, sub, query):
        s = self.store
        if not sub:
            return 200, _json_bytes(s.run_summary(run_id)), "application/json"
        if sub == ["tree"]:
            return 200, _json_bytes(s.tree(run_id)), "application/json"
        if sub == ["spans"]:
            return 200, _json_bytes(s.spans(run_id)), "application/json"
        if len(sub) == 2 and sub[0] == "model_calls":
            return 200, _json_bytes(s.model_call(run_id, sub[1])), "application/json"
        if sub == ["events"]:  # recorded trace log replay
            return 200, _json_bytes({"events": s.trace_events(run_id)}), "application/json"
        if len(sub) == 2 and sub[0] == "candidates":
            return 200, _json_bytes(s.candidate(run_id, sub[1])), "application/json"
        if len(sub) == 3 and sub[0] == "candidates" and sub[2] == "diff":
            cand = s.candidate(run_id, sub[1])
            parent_id = (query.get("against", [None])[0]) or cand.get("parent_candidate_id")
            if not parent_id:
                return 200, _json_bytes({"error": "NO_PARENT", "diff": None,
                                         "note": "root candidate or parent unknown"}), "application/json"
            parent = s.candidate(run_id, parent_id)
            pw, cw = parent["files"].get("workflow"), cand["files"].get("workflow")
            if not pw or not cw:
                return 200, _json_bytes({"error": "ARTIFACT_MISSING", "diff": None,
                                         "note": "workflow snapshot missing for parent or child"}), "application/json"
            d = diffmod.diff_workflows(pw["data"], cw["data"])
            d["parent_candidate_id"] = parent_id
            d["parent_sha256"] = pw["sha256"]
            d["child_sha256"] = cw["sha256"]
            return 200, _json_bytes(d), "application/json"
        if sub == ["metrics"]:
            summ = s.run_summary(run_id)
            tree = s.tree(run_id)
            spans = s.spans(run_id)
            valid = sum(1 for n in tree["nodes"] if n["valid"] is True)
            invalid = sum(1 for n in tree["nodes"] if n["valid"] is False)
            unknown = sum(1 for n in tree["nodes"] if n["valid"] is None)
            tokens = sum((sp.get("tokens") or {}).get("total_token_count", 0) for sp in spans["spans"])
            return 200, _json_bytes({
                "run": summ, "candidates": {"total": len(tree["nodes"]), "valid": valid,
                                            "invalid": invalid, "unknown": unknown},
                "tokens_total": tokens or None,
                "model_calls": sum(1 for sp in spans["spans"] if sp["kind"] == "llm"),
                "warnings": tree["warnings"] + spans["warnings"],
            }), "application/json"
        if sub == ["artifact"]:
            rel = query.get("path", [""])[0]
            data, suffix = s.artifact(run_id, rel)
            ctype = "application/json" if suffix in ("json", "jsonl") else "text/plain; charset=utf-8"
            return 200, data, ctype
        if sub == ["stream"]:
            return 200, b"", "text/event-stream"  # handled by handle_stream
        return 404, _json_bytes({"error": "NOT_FOUND"}), "application/json"

    # ---------------------------------------------------------------- SSE

    def stream(self, run_id: str, write, should_continue) -> None:
        """Push a 'changed' event when any file in the run dir changes.

        Client refetches snapshots; server never blocks the builder.
        """
        s = self.store
        try:
            d = s.run_dir(run_id)
        except RunNotFound:
            write(b"event: error\ndata: {\"error\": \"RUN_NOT_FOUND\"}\n\n")
            return
        write(("event: snapshot\ndata: %s\n\n" % json.dumps(
            {"run_id": run_id, "time": _now()})).encode())

        def snapshot_stats():
            stats = {}
            for p in d.rglob("*"):
                if p.is_file():
                    try:
                        st = p.stat()
                        stats[str(p)] = (st.st_mtime_ns, st.st_size)
                    except OSError:
                        pass
            return stats

        stats = snapshot_stats()
        last_beat = time.time()
        while should_continue():
            time.sleep(POLL_SECONDS)
            cur = snapshot_stats()
            if cur != stats:
                stats = cur
                write(("event: changed\ndata: %s\n\n" % json.dumps(
                    {"run_id": run_id, "time": _now()})).encode())
            elif time.time() - last_beat > HEARTBEAT_SECONDS:
                write(b": heartbeat\n\n")
                last_beat = time.time()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def make_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet
            pass

        def do_GET(self):
            u = urlparse(self.path)
            query = parse_qs(u.query)
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 4 and parts[3] == "stream":
                self._serve_stream(parts[2])
                return
            status, body, ctype = studio.handle("GET", u.path, query)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_stream(self, run_id):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            def write(b: bytes):
                try:
                    self.wfile.write(b)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    raise _StopStream()

            class _Flag:
                stop = False

            flag = _Flag()

            def should_continue():
                return not flag.stop

            try:
                studio.stream(run_id, write, should_continue)
            except _StopStream:
                pass
            finally:
                flag.stop = True
                self.close_connection = True

    class _StopStream(Exception):
        pass

    return Handler


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m observability.serve",
                                 description="Freya Builder Studio (read-only)")
    ap.add_argument("--artifacts-dir", default=os.environ.get("OBS_ARTIFACTS_DIR",
                   os.environ.get("ARTIFACTS_DIR", "agent/artifacts")))
    ap.add_argument("--host", default=os.environ.get("OBS_SERVER_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("OBS_SERVER_PORT", "8765")))
    args = ap.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing non-loopback bind without auth (see ticket-03 §10)")
    studio = Studio(args.artifacts_dir)
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(studio))
    print(f"Freya Builder Studio → http://{args.host}:{args.port}  (artifacts: {args.artifacts_dir})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
