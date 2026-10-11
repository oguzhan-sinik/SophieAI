"""Smoke-test the setup in env.sh: required vars present, Modal LLM reachable, Freya API works.

    source env.sh && python3 tools/smoke_test.py            # cheap checks
    source env.sh && python3 tools/smoke_test.py --live     # + one real LLM completion (costs a few tokens)
"""
import json, os, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import freya

REQUIRED = ["FREYA_API_KEY", "FREYA_BANK_TEAM_KEY", "MODAL_BASE_URL", "MODAL_KEY",
            "MODAL_SECRET", "BUILDER_MODEL", "MUTATOR_MODEL", "REFEREE_MODEL"]

def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status, json.loads(res.read())

failures = []
for var in REQUIRED:
    if os.environ.get(var):
        print(f"ok   {var} set")
    else:
        failures.append(f"{var} empty — fill it in env.sh")

model = os.environ.get("BUILDER_MODEL", "")
base = os.environ.get("MODAL_BASE_URL", "")
if base and model:
    try:
        served = model.split("/", 1)[1]
        root = base.rstrip("/")
        if not root.endswith("/v1"):
            root += "/v1"
        status, body = get(root + "/models",
                           {"Modal-Key": os.environ["MODAL_KEY"], "Modal-Secret": os.environ["MODAL_SECRET"]})
        names = [m.get("id") for m in body.get("data", [])]
        if served in names:
            print(f"ok   Modal serves {served}")
        else:
            failures.append(f"Modal /v1/models has {names}, expected {served} (BUILDER_MODEL)")
    except Exception as e:
        failures.append(f"Modal unreachable at {base}: {e}")

if "--live" in sys.argv and base and model and not failures:
    try:
        served = model.split("/", 1)[1]
        body = json.dumps({"model": served, "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                           "max_tokens": 2000, "chat_template_kwargs": {"enable_thinking": False}}).encode()
        req = urllib.request.Request(root + "/chat/completions", data=body, method="POST",
                                     headers={"Modal-Key": os.environ["MODAL_KEY"], "Modal-Secret": os.environ["MODAL_SECRET"],
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as res:
            out = json.loads(res.read())
        text = (out["choices"][0]["message"].get("content") or "").strip()
        if text:
            print(f"ok   Modal completion: {text[:60]!r}")
        else:
            failures.append(f"Modal completion returned empty content: {str(out)[:200]}")
    except Exception as e:
        failures.append(f"Modal completion failed: {e}")

if os.environ.get("FREYA_API_KEY"):
    try:
        wid = freya.workspace_id()
        if wid:
            print(f"ok   Freya workspace {wid}")
        else:
            failures.append(f"Freya API answered but no workspace id: {str(body)[:200]}")
    except Exception as e:
        failures.append(f"Freya API failed: {e}")

if failures:
    print("\nFAIL:")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("\nall good")
