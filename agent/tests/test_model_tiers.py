"""TICKET-05: per-role model tiers route, override and fail closed; no network calls."""
import pytest

from pydantic import BaseModel

from builder.adk import ADKRoles
from builder.config import Config, Deadline, missing_credentials, role_tier, tier_models


HARD = "openrouter/openai/gpt-6.1-sol"
MEDIUM = "openrouter/openai/gpt-6-luna-pro"
EASY = "openrouter/deepseek/deepseek-v4.1-flash"


class Reply(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("BUILDER_MODEL", "MODEL_TIER_HARD", "MODEL_TIER_MEDIUM", "MODEL_TIER_EASY", "ROLE_MODELS",
                 "OPENROUTER_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "DOUBLEWORD_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # A developer's ignored env.sh must not override the test's tier defaults.
    for name in ("MODEL_TIER_HARD", "MODEL_TIER_MEDIUM", "MODEL_TIER_EASY", "ROLE_MODELS"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("MODAL_BASE_URL", "https://modal-fixture.invalid/v1")
    monkeypatch.setenv("MODAL_KEY", "modal-key-fixture")
    monkeypatch.setenv("MODAL_SECRET", "modal-secret-fixture")


def test_default_tiers_follow_the_documented_split(monkeypatch):
    monkeypatch.setenv("BUILDER_MODEL", HARD)
    cfg = Config(builder_model=HARD)
    assert cfg.role_model("BriefAnalystAgent") == HARD
    assert cfg.role_model("ADASDesignerAgent") == HARD and cfg.role_model("FixAgent") == HARD
    assert cfg.role_model("synthetic_source_analyst") == HARD
    assert cfg.role_model("synthetic_transcript_judge") == MEDIUM
    assert cfg.role_model("synthetic_brief_writer") == MEDIUM
    assert cfg.role_model("synthetic_customer_validator") == MEDIUM
    assert cfg.role_model("synthetic_customer") == EASY
    assert cfg.role_model("proxy_extractor") == EASY and cfg.role_model("proxy_dialogue") == EASY
    assert cfg.role_model("unknown_role") == HARD  # roles default to the hard tier
    assert role_tier("FixAgent") == "hard" and role_tier("proxy_router") == "easy"


def test_env_overrides_replace_tiers_then_single_roles(monkeypatch):
    monkeypatch.setenv("BUILDER_MODEL", HARD)
    monkeypatch.setenv("MODEL_TIER_MEDIUM", "doubleword/zai-org/GLM-5.3-Flash")
    monkeypatch.setenv("MODEL_TIER_EASY", "qwencloud/qwen3.8-max-0902")
    cfg = Config.from_env()
    assert cfg.role_model("synthetic_transcript_reviewer") == "doubleword/zai-org/GLM-5.3-Flash"
    assert cfg.role_model("proxy_router") == "qwencloud/qwen3.8-max-0902"
    monkeypatch.setenv("ROLE_MODELS", "synthetic_customer=modal/Qwen/Qwen3.8-2.4T-A95B, brokenpair")
    cfg = Config.from_env()
    assert cfg.role_model("synthetic_customer") == "modal/Qwen/Qwen3.8-2.4T-A95B"
    assert cfg.role_model("proxy_router") == "qwencloud/qwen3.8-max-0902"  # tier still applies
    assert tier_models(HARD)["hard"] == HARD  # unset MODEL_TIER_HARD falls back to BUILDER_MODEL


def test_from_env_freezes_role_assignment_for_the_run(monkeypatch):
    monkeypatch.setenv("BUILDER_MODEL", HARD)
    cfg = Config.from_env()
    before = cfg.models.copy()
    monkeypatch.setenv("MODEL_TIER_EASY", "openrouter/openai/gpt-6-luna-pro")
    assert cfg.models == before
    assert cfg.role_model("synthetic_customer") == EASY


def test_missing_credentials_cover_every_tier_provider(monkeypatch):
    monkeypatch.setenv("BUILDER_MODEL", HARD)
    monkeypatch.setenv("FREYA_API_KEY", "freya-fixture")
    monkeypatch.setenv("FREYA_BANK_TEAM_KEY", "bank-fixture")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-fixture")
    assert missing_credentials(Config.from_env()) == []
    monkeypatch.setenv("OPENROUTER_API_KEY", "")  # blank reloads from env.sh count as unset
    # Default medium/easy tiers ride OpenRouter, so its key is required even with a non-OpenRouter primary.
    assert missing_credentials(Config(builder_model="modal/Qwen/Qwen3.8-2.4T-A95B")) == ["OPENROUTER_API_KEY"]
    monkeypatch.setenv("MODEL_TIER_MEDIUM", "qwencloud/qwen3.8-max-0902")
    monkeypatch.setenv("MODEL_TIER_EASY", "qwencloud/qwen3.8-max-0902")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    assert missing_credentials(Config(builder_model="modal/Qwen/Qwen3.8-2.4T-A95B")) == ["DASHSCOPE_API_KEY"]


def test_adk_request_serves_each_role_from_its_tier(work, monkeypatch):
    from builder.artifacts import Trace
    monkeypatch.setenv("BUILDER_MODEL", HARD)
    seen = {}

    async def scripted_ask(role, instruction, payload, schema, model, max_tokens):
        seen[role] = model
        return '{"ok":true}', []

    roles = ADKRoles(Config(builder_model=HARD), Deadline(60), Trace(work / "trace.log", {"run_id": "t"}, False), work)
    roles._ask = scripted_ask
    roles.ask("FixAgent", "p", "i", {}, Reply)
    roles.ask("synthetic_customer", "p", "i", {}, Reply)
    assert seen == {"FixAgent": HARD, "synthetic_customer": EASY}


def test_doubleword_kwargs_adapt_per_upstream_model(monkeypatch):
    from builder.adk import doubleword_litellm_kwargs
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "fixture")
    glm = doubleword_litellm_kwargs("doubleword/zai-org/GLM-5.3-Flash", Reply, 25)
    assert glm["allowed_openai_params"] == ["reasoning_effort"] and "response_format" in glm
    qwen = doubleword_litellm_kwargs("doubleword/Qwen/Qwen3.5-397B-A17B-FP8", Reply, 25)
    assert qwen["extra_body"] == {"reasoning_effort": "low"} and "allowed_openai_params" not in qwen and "response_format" in qwen
    pro = doubleword_litellm_kwargs("doubleword/deepseek-ai/DeepSeek-V4-Pro", Reply, 25)
    assert not {"reasoning_effort", "allowed_openai_params", "response_format"} & pro.keys()
