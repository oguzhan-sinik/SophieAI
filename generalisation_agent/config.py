"""Environment gates read once at startup, before models or mock state are created."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def model_settings(model):
    """Describe one model's endpoint settings, or a {tier/role: model} map (TICKET-05)."""
    if isinstance(model, dict):
        return {name: model_settings(one) for name, one in sorted(model.items())}
    endpoints = {"modal/": ("MODAL_BASE_URL", ""),
                 "doubleword/": ("DOUBLEWORD_BASE_URL", "https://api.doubleword.ai/v1"),
                 "qwencloud/": ("QWENCLOUD_BASE_URL", "https://maas.qwencloudapi.com/compatible-mode/v1"),
                 "openrouter/": (None, "https://openrouter.ai/api/v1")}
    for prefix, (variable, default) in endpoints.items():
        if model.startswith(prefix):
            endpoint = ((os.getenv(variable, "").strip() or default) if variable else default).rstrip("/")
            if prefix in {"modal/", "doubleword/"} and not endpoint.endswith("/v1"): endpoint += "/v1"
            return {"model": model, "endpoint": endpoint,
                    "thinking": os.getenv("MODAL_ENABLE_THINKING", "false").lower() == "true" if prefix == "modal/" else prefix == "qwencloud/",
                    "modal_json_schema": os.getenv("MODAL_JSON_SCHEMA", "true").lower() == "true" if prefix == "modal/" else None,
                    "qwen_min_output_tokens": 65536 if model.startswith("qwencloud/") else None,
                    "doubleword_reasoning": "writer/checker=medium;other=low" if model.startswith("doubleword/") else None}
    return {"model": model}


def switch(name, default):
    value = os.environ.get(name, str(default).lower())
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    briefs: bool = True
    users: bool = True

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        from agent.builder.config import load_env
        load_env()
        return cls(switch("GENERALISATION_ENABLED", False),
                   switch("GENERALISATION_BRIEFS_ENABLED", True),
                   switch("GENERALISATION_USERS_ENABLED", True))

    def require(self, feature):
        if not self.enabled or not getattr(self, feature):
            raise ValueError(f"Synthetic {feature} disabled by environment configuration")

    def manifest(self):
        return {"GENERALISATION_ENABLED": self.enabled,
                "GENERALISATION_BRIEFS_ENABLED": self.briefs,
                "GENERALISATION_USERS_ENABLED": self.users}


def confined(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Generalisation output must stay inside {ROOT}")
    return path
