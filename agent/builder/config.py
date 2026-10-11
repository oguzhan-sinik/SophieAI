"""Validated configuration; writable paths stay inside the two builder directories."""
from dataclasses import dataclass, field
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


# TICKET-05: role -> model tier. Hard roles decide what is built and feed
# calibration; medium roles are bounded independent checks; easy roles are
# short, high-volume per-turn calls where the cheap model saves the most.
TIER_ROLES = {
    "hard": ("BriefAnalystAgent", "ADASDesignerAgent", "FixAgent", "synthetic_source_analyst"),
    "medium": ("synthetic_brief_writer", "synthetic_brief_checker", "synthetic_transcript_judge",
               "synthetic_transcript_reviewer", "synthetic_customer_validator",
               "synthetic_transcript_validator", "synthetic_live_judge", "synthetic_live_reviewer"),
    "easy": ("synthetic_customer_listener", "synthetic_customer",
             "proxy_router", "proxy_dialogue", "proxy_extractor"),
}
# The roles of a plain build. Everything else belongs to the generalisation extension.
BUILDER_ROLES = ("BriefAnalystAgent", "ADASDesignerAgent", "FixAgent")
TIER_DEFAULTS = {"medium": "openrouter/openai/gpt-6-luna-pro",
                 "easy": "openrouter/deepseek/deepseek-v4.1-flash"}


def role_tier(role):
    return next((tier for tier, roles in TIER_ROLES.items() if role in roles), "hard")


def tier_models(builder_model):
    """Resolved {tier or role: model}. MODEL_TIER_* replaces a tier; ROLE_MODELS pins one role."""
    models = {"hard": os.getenv("MODEL_TIER_HARD", "").strip() or builder_model}
    for tier, default in TIER_DEFAULTS.items():
        models[tier] = os.getenv("MODEL_TIER_" + tier.upper(), "").strip() or default
    for pair in filter(None, os.getenv("ROLE_MODELS", "").split(",")):
        role, _, model = pair.partition("=")
        if role.strip() and model.strip():
            models[role.strip()] = model.strip()
    return models


@dataclass(frozen=True)
class Config:
    builder_model: str = "modal/Qwen/Qwen3.8-2.4T-A95B"
    max_wall_seconds: int = 10800      # no build has needed three hours; a limit below what a case needs builds nothing
    reserve: int = 180
    repetitions: int = 1
    max_simulations: int = 4
    llm_timeout: int = 1800           # one model call; a large case is read slowly, and a cut-off call is a lost one
    request_timeout: int = 90
    official: bool = True
    tracing: bool = True
    artifacts: Path = AGENT / "artifacts"
    runtime: Path = AGENT / ".runtime"
    role_models: dict = field(default=None)

    def __post_init__(self):
        if self.max_wall_seconds < 30:
            raise ValueError("MAX_WALL_SECONDS must be at least 30")
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
        builder_model = os.getenv("BUILDER_MODEL") or cls.builder_model
        return cls(**values, builder_model=builder_model, role_models=tier_models(builder_model),
                   official=boolean("EVAL_ENABLE_OFFICIAL_PUBLIC", True), tracing=boolean("LANGSMITH_TRACING", True),
                   artifacts=writable(AGENT / os.getenv("ARTIFACTS_DIR", "artifacts")))

    @property
    def models(self):
        return self.role_models or tier_models(self.builder_model)

    def role_model(self, role):
        models = self.models
        return models.get(role) or models[role_tier(role)]


PROVIDER_KEYS = {"modal/": ("MODAL_BASE_URL", "MODAL_KEY", "MODAL_SECRET"), "doubleword/": ("DOUBLEWORD_API_KEY",), "qwencloud/": ("DASHSCOPE_API_KEY",), "openrouter/": ("OPENROUTER_API_KEY",), "anthropic/": ("ANTHROPIC_API_KEY",),
                 "gemini/": ("GOOGLE_API_KEY",), "gemini-": ("GOOGLE_API_KEY",), "openai/": ("OPENAI_API_KEY",)}


def missing_credentials(cfg, roles=None):
    """Names (never values) of required keys that are unset for this configuration.

    Every tier's provider is covered unless `roles` names the only roles that will run: a plain
    build calls three, and must not be refused for the key of a model it never uses."""
    need = {"FREYA_API_KEY", "FREYA_BANK_TEAM_KEY"}
    models = {cfg.role_model(role) for role in roles} if roles else set(cfg.models.values())
    for prefix, keys in PROVIDER_KEYS.items():
        if any(model.startswith(prefix) for model in models):
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
