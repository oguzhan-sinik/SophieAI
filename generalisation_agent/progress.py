"""What the dashboard may see of synthetic work.

Model progress always. For diagnostics that replay the supplied practice scripts, also the test
itself: its events and a copy of the per-customer results and conversations. Those scripts are
public, so the copy shows nothing a build must not see; generated customers and holdout packs are
never passed to `mirrored` and stay private."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading

from agent.builder.artifacts import encoded, write_json
from agent.builder.config import AGENT, writable

EVENTS = {"run_start", "run_end", "ADKModelCall_start", "ADKModelCall_end",
          "ADKModelCall_error", "model_usage", "structured_output_retry",
          "synthetic_render_accepted", "synthetic_render_rejected",
          "synthetic_users_generated", "synthetic_packs_generated"}
FIELDS = {"at", "event", "component", "model", "role", "call_id", "status", "error",
          "pack", "attempt", "case_count"}
# A practice-script diagnostic appears as a test, like the official one. Its extra fields are
# published for these events only: a model call's message can quote a private answer.
TEST_EVENTS = {"FreyaDeploy_start", "FreyaDeploy_end", "FreyaDeploy_error", "candidate_published",
               "OfficialBenchmark_start", "OfficialBenchmark_end", "OfficialBenchmark_error",
               "official_result", "benchmark_incomplete"}
TEST_FIELDS = {"evaluation_folder", "repetition", "passed", "total", "version", "steps", "tools", "slot", "message"}
VIEW = ("raw_runner.json", "calls_*.json", "live_*.json", "live_calls_*.json")


@contextmanager
def mirrored(private, public):
    """While the block runs, and once more when it ends, copy what the dashboard reads of a test
    from its private folder to `public`, a folder under the dashboard's root."""
    private = Path(private)
    try:
        public = writable(public)
    except ValueError:
        yield None   # nowhere the dashboard reads: the test runs unmirrored
        return
    stop = threading.Event()

    def copy():
        for pattern in VIEW:
            for path in private.glob(pattern):
                target = public / path.name
                try:
                    if not target.exists() or target.stat().st_mtime < path.stat().st_mtime:
                        public.mkdir(parents=True, exist_ok=True)
                        pending = target.with_name(target.name + ".pending")
                        pending.write_bytes(path.read_bytes())
                        pending.replace(target)
                except OSError:
                    pass   # a file caught mid-write is picked up on the next pass

    def keep_copying():
        while not stop.wait(5):
            copy()

    thread = threading.Thread(target=keep_copying, daemon=True)
    thread.start()
    try:
        yield public
    finally:
        stop.set()
        thread.join(timeout=10)
        copy()
TOKEN_FIELDS = {"cached_content_token_count", "candidates_token_count", "prompt_token_count",
                "thoughts_token_count", "total_token_count"}


def publish_event(run_id, record):
    if record.get("event") not in EVENTS | TEST_EVENTS:
        return
    public = writable(AGENT / "artifacts" / ("synthetic_" + run_id))
    public.mkdir(parents=True, exist_ok=True)
    allowed = FIELDS | TEST_FIELDS if record.get("event") in TEST_EVENTS else FIELDS
    event = {k: v for k, v in record.items() if k in allowed and isinstance(v, (str, int, float, bool, type(None)))}
    if record.get("event") == "model_usage":
        event["tokens"] = [{k: v for k, v in usage.items() if k in TOKEN_FIELDS and type(v) is int}
                           for usage in record.get("tokens", []) if isinstance(usage, dict)]
    if event["event"] == "run_start":
        write_json(public / "manifest.json", {"run_id": public.name, "start": event.get("at"),
                   "config": {"mode": "synthetic_progress", "builder_model": event.get("model")}})
    with (public / "build_trace.log").open("a") as stream:
        stream.write(encoded(event) + "\n")
        stream.flush()
    if event["event"] == "run_end":
        write_json(public / "report.json", {"status": event.get("status"), "end": event.get("at"),
                   "mode": "synthetic_progress", "error": event.get("error")})


def publish_progress(trace):
    """Attach after trace construction, replaying its initial event once."""
    run_id = trace.path.parent.name
    trace.observer = lambda record: publish_event(run_id, record)
    for line in trace.path.read_text().splitlines():
        trace.observer(json.loads(line))
