"""A small agentic builder: the model reads the brief, writes the phone agent, tests it and fixes it.

    pip install google-adk litellm
    # put NVIDIA_API_KEY=nvapi-... in .env (next to freya.py)
    python3 agent/agent_builder.py briefs/brief-a.md

Runs Google ADK with the free NVIDIA NIM GLM model (via LiteLLM). Keys come from .env —
no terminal exports needed. The builder's knowledge lives in
.claude/skills/build-phone-agent/SKILL.md, inlined as the agent instruction.
Every message of the run is written to traces/<start time>.jsonl. That file is the trace you submit.
"""
import json, os, pathlib, subprocess, sys, time

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

KIT = pathlib.Path(__file__).resolve().parent.parent
MODEL = os.environ.get("BUILDER_MODEL", "nvidia_nim/z-ai/glm-5.3")


def load_env(path=KIT / ".env"):  # ponytail: handles KEY=v and export KEY=v; strips quotes
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env()


def safe(path):  # ponytail: clamp to kit folder; model runs unsandboxed otherwise
    p = (KIT / path).resolve()
    if not p.is_relative_to(KIT):
        raise ValueError(f"outside kit: {path}")
    return p


def bash(cmd: str) -> str:
    """Run a shell command in the kit folder, return stdout+stderr."""
    r = subprocess.run(cmd, shell=True, cwd=KIT, capture_output=True, text=True, timeout=1200)
    return ((r.stdout or "") + (r.stderr or ""))[-20000:] or "(no output)"


def read_file(path: str) -> str:
    """Read a file in the kit folder."""
    return safe(path).read_text(errors="replace")[:50000]


def write_file(path: str, content: str) -> str:
    """Create/overwrite a file in the kit folder."""
    p = safe(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {path} ({len(content)} bytes)"


def main(briefs):
    trace = KIT / "traces" / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
    trace.parent.mkdir(exist_ok=True)
    skill = (KIT / ".claude/skills/build-phone-agent/SKILL.md").read_text()
    agent = LlmAgent(
        name="builder",
        model=LiteLlm(model=MODEL, api_key=os.environ["NVIDIA_API_KEY"]),
        instruction="You are an agentic builder. Work in the kit folder using your tools.\n\n" + skill,
        tools=[bash, read_file, write_file],
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(app_name="builder", user_id="dev")
    runner = Runner(agent=agent, app_name="builder", session_service=session_service)
    prompt = "Use the build-phone-agent skill to build a phone agent for: " + " ".join(briefs)
    with trace.open("w") as out:
        out.write(json.dumps({"start": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "briefs": briefs, "model": MODEL}) + "\n")
        turns = 0
        for event in runner.run(user_id="dev", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
            turns += 1
            out.write(json.dumps({"type": "event", "author": event.author, "content": event.model_dump(exclude_none=True)}) + "\n")
            out.flush()
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text, flush=True)
                    elif part.function_call:
                        print(f"  [{part.function_call.name}] {str(part.function_call.args)[:120]}", flush=True)
        print(f"\ndone: {turns} events. Trace: {trace}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
