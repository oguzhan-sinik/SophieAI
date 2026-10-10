"""Validated configuration; every writable path is constrained to agent/."""
from dataclasses import dataclass
import os
from pathlib import Path
import time

AGENT = Path(__file__).resolve().parents[1]
KIT = AGENT.parent
MODES = ("scoring_only", "scoring_with_diagnostics")


def writable(path):
    path = Path(path).resolve()
    if not path.is_relative_to(AGENT):
        raise ValueError(f"Output must stay inside {AGENT}: {path}")
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
    mode: str = "scoring_with_diagnostics"
    builder_model: str = "modal/Qwen/Qwen3.8-2.4T-A95B"
    mutator_model: str = "modal/Qwen/Qwen3.8-2.4T-A95B"
    referee_model: str = "modal/Qwen/Qwen3.8-2.4T-A95B"
    max_wall_seconds: int = 1800
    reserve: int = 180
    max_candidates: int = 10
    max_depth: int = 3
    beam_width: int = 2
    group_size: int = 3
    seed: int = 42
    repetitions: int = 1
    final_repetitions: int = 3
    max_simulations: int = 2
    llm_timeout: int = 480
    request_timeout: int = 90
    official: bool = True
    tracing: bool = True
    artifacts: Path = AGENT / "artifacts"

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"BENCHMARK_MODE must be one of {MODES}")
        if not 30 <= self.max_wall_seconds <= 1800:
            raise ValueError("MAX_WALL_SECONDS must be between 30 and 1800")
        if not 1 <= self.reserve < self.max_wall_seconds:
            raise ValueError("Export reserve must be positive and below build budget")
        for key in ("max_candidates", "beam_width", "group_size", "repetitions", "final_repetitions", "llm_timeout", "request_timeout"):
            if getattr(self, key) < 1:
                raise ValueError(f"{key} must be positive")
        if self.max_depth < 0 or self.max_simulations < 0:
            raise ValueError("Depth and simulation budget cannot be negative")
        writable(self.artifacts)

    @classmethod
    def from_env(cls, mode=None):
        load_env()
        model = os.getenv("BUILDER_MODEL") or cls.builder_model
        ints = {"max_wall_seconds": "MAX_WALL_SECONDS", "reserve": "MIN_EXPORT_RESERVE_SECONDS", "max_candidates": "MAX_CANDIDATES", "max_depth": "MAX_TREE_DEPTH", "beam_width": "BEAM_WIDTH", "group_size": "GROUP_SIZE", "seed": "SEARCH_SEED", "repetitions": "EVAL_REPETITIONS", "final_repetitions": "EVAL_FINAL_REPETITIONS", "max_simulations": "EVAL_MAX_SIMULATIONS", "llm_timeout": "LLM_CALL_TIMEOUT_SECONDS", "request_timeout": "FREYA_REQUEST_TIMEOUT_SECONDS"}
        values = {k: int(os.getenv(v, str(getattr(cls, k)))) for k, v in ints.items()}
        if os.getenv("FREYA_MAX_CONCURRENT_SIMULATIONS", "1") != "1":
            raise ValueError("Freya permits exactly one simulation at a time")
        return cls(**values, mode=mode or os.getenv("BENCHMARK_MODE", cls.mode), builder_model=model,
                   mutator_model=os.getenv("MUTATOR_MODEL") or model, referee_model=os.getenv("REFEREE_MODEL") or cls.referee_model,
                   official=boolean("EVAL_ENABLE_OFFICIAL_PUBLIC", True), tracing=boolean("LANGSMITH_TRACING", True),
                   artifacts=writable(AGENT / os.getenv("ARTIFACTS_DIR", "artifacts")))


PROVIDER_KEYS = {"modal/": ("MODAL_BASE_URL", "MODAL_KEY", "MODAL_SECRET"), "anthropic/": ("ANTHROPIC_API_KEY",),
                 "gemini/": ("GOOGLE_API_KEY",), "gemini-": ("GOOGLE_API_KEY",), "openai/": ("OPENAI_API_KEY",)}


def missing_credentials(cfg, need_models=True):
    """Names (never values) of required keys that are unset for this configuration."""
    need = {"FREYA_API_KEY", "FREYA_BANK_TEAM_KEY"}
    if need_models:
        for model in {cfg.builder_model, cfg.mutator_model, cfg.referee_model}:
            for prefix, keys in PROVIDER_KEYS.items():
                if model.startswith(prefix):
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
