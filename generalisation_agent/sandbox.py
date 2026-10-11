"""Actual Python in a disposable container; no host paths or credentials enter it."""
import json
import subprocess
import uuid

from agent.builder.validation import code_errors

IMAGE = "python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
HARNESS = r'''
import json, sys, resource, datetime, re, _strptime
payload = json.loads(sys.stdin.read(1048577))
resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
def audit(event, args):
    if event == "open" or event.startswith(("socket.", "subprocess.", "os.", "ctypes.", "shutil.")):
        raise PermissionError("File, process and network capabilities are denied")
sys.addaudithook(audit)
namespace = {"vars": payload["vars"], "config": payload.get("config", {}), "result": payload.get("result", {})}
class Sink:
    def write(self, text): return len(text)
    def flush(self): pass
stdout = sys.stdout
sys.stdout = Sink()
sys.stderr = Sink()
try:
    exec(compile(payload["code"], "<workflow>", "exec"), namespace, namespace)
    output = {key: namespace[key] for key in ("vars", "config", "result")}
    result = json.dumps(output, allow_nan=False)
    if len(result) > 1048576: raise ValueError("Code output exceeds one MiB")
    print(result, file=stdout)
except BaseException as exc:
    print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)[:300]}), file=stdout)
'''


class Unsupported(RuntimeError):
    pass


class DockerCode:
    def __init__(self, deadline, image=IMAGE):
        self.deadline, self.image = deadline, image

    def ready(self):
        try:
            result = subprocess.run(["docker", "image", "inspect", self.image, "--format", "{{.Id}}"],
                                    capture_output=True, text=True, timeout=self.deadline.timeout(10))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Unsupported("Docker runtime unavailable") from exc
        if result.returncode:
            # Some containerd stores lose the digest ref while the image stays runnable; verify the
            # exact pinned digest by actually resolving it with --pull=never, never a different image.
            probe = subprocess.run(["docker", "run", "--rm", "--pull=never", "--network=none", self.image,
                                    "python", "-I", "-B", "-S", "-c", "pass"],
                                   capture_output=True, text=True, timeout=self.deadline.timeout(30))
            if probe.returncode:
                raise Unsupported(f"Docker/image unavailable; prepare with docker pull {self.image}")

    def run(self, code, variables, config=None, result=None):
        errors = code_errors(code, hook=config is not None or result is not None)
        if errors:
            raise Unsupported("Code capability check: " + "; ".join(errors))
        payload = json.dumps({"code": code, "vars": variables, "config": config or {}, "result": result or {}}, allow_nan=False)
        if len(payload.encode()) > 1048576:
            raise Unsupported("Code input exceeds one MiB")
        name = "freya-local-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--pull=never", "--name", name, "--network=none", "--read-only",
                   "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--user=65534:65534", "--log-driver=none", "-i",
                   self.image, "python", "-I", "-B", "-S", "-c", HARNESS]
        try:
            process = subprocess.run(command, input=payload, text=True, capture_output=True,
                                     timeout=self.deadline.timeout(10))
            if process.returncode or len(process.stdout) > 1048576:
                raise Unsupported("Code container failed or exceeded its resource limit: " + process.stderr[:200])
            output = json.loads(process.stdout)
            if "error" in output:
                raise Unsupported("Code execution failed: " + output["error"])
            if set(output) != {"vars", "config", "result"} or not isinstance(output["vars"], dict):
                raise Unsupported("Code returned invalid state")
            return output
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise Unsupported("Code runtime interrupted: " + type(exc).__name__) from exc
        finally:
            # Killing the client alone does not stop a timed-out Docker container.
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
