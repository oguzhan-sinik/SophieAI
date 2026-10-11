"""Validated configuration; writable paths stay inside the two builder directories."""
from dataclasses import dataclass
import os
from pathlib import Path
import time

AGENT = Path(__file__).resolve().parents[1]
KIT = AGENT.parent
GENERALISATION = KIT / "generalisation_agent"


def writable(path):
    path = Path(path).resolve()
    if not any(path.is_relative_to(root) for root in (AGENT, GENERALISATION)):
        raise ValueError(f"Output must stay inside {AGENT} or {GENERALISATION}: {path}")
    return path


def load_env():
    from dotenv import load_dotenv
    # Process environment wins; agent settings override kit defaults.
    load_dotenv(AGENT / ".env", override=False)
    load_dotenv(KIT / ".env", override=False)
    # env.sh uses `export KEY=value`, which python-dotenv reads directly.
    load_dotenv(KIT / "env.sh", override=False)
    # `KEY=   # note` is read by python-dotenv as the value "# note"; an empty setting must stay empty.
    for key, value in list(os.environ.items()):
        if value.lstrip().startswith("#") and key.isupper():
            os.environ[key] = ""


def boolean(name, default):
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Config:
    builder_model: str = "modal/Qwen/Qwen3.8-2.4T-A95B"
    max_wall_seconds: int = 1800
    reserve: int = 180
    repetitions: int = 1
    max_simulations: int = 4
    llm_timeout: int = 480
    request_timeout: int = 90
    official: bool = True
    tracing: bool = True
    artifacts: Path = AGENT / "artifacts"
    runtime: Path = AGENT / ".runtime"

    def __post_init__(self):
        if not 30 <= self.max_wall_seconds <= 1800:
            raise ValueError("MAX_WALL_SECONDS must be between 30 and 1800")
        if not 1 <= self.reserve < self.max_wall_seconds:
            raise ValueError("Export reserve must be positive and below build budget")
        for key in ("repetitions", "llm_timeout", "request_timeout"):
            if getattr(self, key) < 1:
                raise ValueError(f"{key} must be positive")
        if self.max_simulations < 0:
            raise ValueError("Simulation budget cannot be negative")
        writable(self.artifacts)
        writable(self.runtime)

    @classmethod
    def from_env(cls):
        load_env()
        ints = {"max_wall_seconds": "MAX_WALL_SECONDS", "reserve": "MIN_EXPORT_RESERVE_SECONDS", "repetitions": "EVAL_REPETITIONS", "max_simulations": "EVAL_MAX_SIMULATIONS",
                "llm_timeout": "LLM_CALL_TIMEOUT_SECONDS", "request_timeout": "FREYA_REQUEST_TIMEOUT_SECONDS"}
        values = {k: int(os.getenv(v, str(getattr(cls, k)))) for k, v in ints.items()}
        if os.getenv("FREYA_MAX_CONCURRENT_SIMULATIONS", "1") != "1":
            raise ValueError("Freya permits exactly one simulation at a time")
        return cls(**values, builder_model=os.getenv("BUILDER_MODEL") or cls.builder_model,
                   official=boolean("EVAL_ENABLE_OFFICIAL_PUBLIC", True), tracing=boolean("LANGSMITH_TRACING", True),
                   artifacts=writable(AGENT / os.getenv("ARTIFACTS_DIR", "artifacts")))


PROVIDER_KEYS = {"modal/": ("MODAL_BASE_URL", "MODAL_KEY", "MODAL_SECRET"), "doubleword/": ("DOUBLEWORD_API_KEY",), "qwencloud/": ("DASHSCOPE_API_KEY",), "openrouter/": ("OPENROUTER_API_KEY",), "anthropic/": ("ANTHROPIC_API_KEY",),
                 "gemini/": ("GOOGLE_API_KEY",), "gemini-": ("GOOGLE_API_KEY",), "openai/": ("OPENAI_API_KEY",)}


def missing_credentials(cfg):
    """Names (never values) of required keys that are unset for this configuration."""
    need = {"FREYA_API_KEY", "FREYA_BANK_TEAM_KEY"}
    for prefix, keys in PROVIDER_KEYS.items():
        if cfg.builder_model.startswith(prefix):
            need |= set(keys)
    return sorted(key for key in need if not os.getenv(key, "").strip())


class Deadline:
    def __init__(self, seconds, reserve=0):
        self.end = time.monotonic() + seconds
        self.reserve = reserve

    def remaining(self, export=False):
        return max(0.0, self.end - time.monotonic() - (0 if export else self.reserve))

    def require(self, seconds=0, export=False):
        if self.remaining(export) <= seconds:
            raise TimeoutError("Build budget exhausted; preserving export reserve")

    def timeout(self, cap, export=False):
        self.require(export=export)
        return min(cap, self.remaining(export))
