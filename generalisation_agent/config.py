"""Environment gates read once at startup, before models or mock state are created."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


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
