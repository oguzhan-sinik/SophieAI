"""Publish only model progress; synthetic evidence stays outside the dashboard."""
import json

from agent.builder.artifacts import encoded, write_json
from agent.builder.config import AGENT, writable

EVENTS = {"run_start", "run_end", "ADKModelCall_start", "ADKModelCall_end",
          "ADKModelCall_error", "model_usage", "structured_output_retry"}
FIELDS = {"at", "event", "component", "model", "role", "call_id", "status", "error"}
TOKEN_FIELDS = {"cached_content_token_count", "candidates_token_count", "prompt_token_count",
                "thoughts_token_count", "total_token_count"}


def publish_event(run_id, record):
    if record.get("event") not in EVENTS:
        return
    public = writable(AGENT / "artifacts" / ("synthetic_" + run_id))
    public.mkdir(parents=True, exist_ok=True)
    event = {k: v for k, v in record.items() if k in FIELDS and isinstance(v, (str, int, float, bool, type(None)))}
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
