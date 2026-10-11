"""Provider routing checks make no network calls and use fixture credentials."""
import asyncio
from types import SimpleNamespace

from pydantic import BaseModel
import pytest

from builder.adk import ADKRoles, doubleword_litellm_kwargs, qwencloud_litellm_kwargs
from builder.config import Config, missing_credentials


class Reply(BaseModel):
    ok: bool


MODEL = "doubleword/zai-org/GLM-5.3-Flash"
QWEN = "qwencloud/qwen3.8-max-0902"


@pytest.mark.parametrize("base", [None, "", "  ", "https://maas.qwencloudapi.com/compatible-mode/v1/"])
def test_qwencloud_thinking_endpoint_and_schema(monkeypatch, base):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-dashscope-key")
    if base is None:
        monkeypatch.delenv("QWENCLOUD_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("QWENCLOUD_BASE_URL", base)
    kwargs = qwencloud_litellm_kwargs(QWEN, Reply, 25)
    assert kwargs["model"] == "openai/qwen3.8-max-0902"
    assert kwargs["api_base"] == "https://maas.qwencloudapi.com/compatible-mode/v1"
    assert kwargs["api_key"] == "fixture-dashscope-key"
    assert kwargs["timeout"] == 25 and kwargs["num_retries"] == 0
    assert kwargs["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in kwargs
    assert kwargs["response_format"]["json_schema"]["schema"] == Reply.model_json_schema()


def test_missing_qwencloud_key_never_falls_back(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", " ")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture")
    with pytest.raises(KeyError, match="DASHSCOPE_API_KEY"):
        qwencloud_litellm_kwargs(QWEN, Reply, 25)
    monkeypatch.setenv("FREYA_API_KEY", "freya-fixture")
    monkeypatch.setenv("FREYA_BANK_TEAM_KEY", "bank-fixture")
    assert missing_credentials(Config(builder_model=QWEN)) == ["DASHSCOPE_API_KEY"]
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-fixture")
    assert missing_credentials(Config(builder_model=QWEN)) == []


@pytest.mark.parametrize("base", [None, "", "  ", "https://api.doubleword.ai", "https://api.doubleword.ai/v1/"])
def test_doubleword_endpoint_model_schema_and_credentials(monkeypatch, base):
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "fixture-doubleword-key")
    if base is None:
        monkeypatch.delenv("DOUBLEWORD_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("DOUBLEWORD_BASE_URL", base)
    monkeypatch.setenv("OPENAI_API_KEY", "different-openai-fixture")
    monkeypatch.setenv("MODAL_KEY", "different-modal-fixture")
    kwargs = doubleword_litellm_kwargs(MODEL, Reply, 25)
    assert kwargs["model"] == "openai/zai-org/GLM-5.3-Flash"
    assert kwargs["api_base"] == "https://api.doubleword.ai/v1"
    assert kwargs["api_key"] == "fixture-doubleword-key"
    assert kwargs["timeout"] == 25 and kwargs["num_retries"] == 0
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["allowed_openai_params"] == ["reasoning_effort"]
    assert kwargs["response_format"]["json_schema"]["schema"] == Reply.model_json_schema()
    assert not {"extra_headers", "extra_body"}.intersection(kwargs)


def test_missing_doubleword_key_fails_without_using_other_provider_key(monkeypatch):
    monkeypatch.setenv("DOUBLEWORD_API_KEY", " ")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture")
    with pytest.raises(KeyError, match="DOUBLEWORD_API_KEY"):
        doubleword_litellm_kwargs(MODEL, Reply, 25)
    monkeypatch.setenv("FREYA_API_KEY", "freya-fixture")
    monkeypatch.setenv("FREYA_BANK_TEAM_KEY", "bank-fixture")
    assert missing_credentials(Config(builder_model=MODEL)) == ["DOUBLEWORD_API_KEY"]
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "doubleword-fixture")
    for key in ("MODAL_BASE_URL", "MODAL_KEY", "MODAL_SECRET", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert missing_credentials(Config(builder_model=MODEL)) == []
    assert set(missing_credentials(Config())) == {"MODAL_BASE_URL", "MODAL_KEY", "MODAL_SECRET"}


@pytest.mark.parametrize("model,role", [(QWEN, "fixture"), (QWEN, "synthetic_brief_writer"),
    (QWEN, "synthetic_brief_checker"), (MODEL, "fixture"), (MODEL, "synthetic_brief_writer"),
    (MODEL, "synthetic_brief_checker"), ("modal/Qwen/fixture", "fixture"),
    ("openai/fixture", "fixture"), ("anthropic/fixture", "fixture"), ("gemini-fixture", "fixture")])
def test_adk_uses_selected_provider_and_preserves_other_routes(monkeypatch, model, role):
    import google.adk.agents
    import google.adk.models.lite_llm
    import google.adk.runners
    from google.adk.agents.run_config import StreamingMode
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-fixture")
    monkeypatch.delenv("QWENCLOUD_BASE_URL", raising=False)
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "doubleword-fixture")
    monkeypatch.setenv("DOUBLEWORD_BASE_URL", "https://api.doubleword.ai/v1")
    monkeypatch.setenv("MODAL_BASE_URL", "https://modal-fixture.invalid/v1")
    monkeypatch.setenv("MODAL_KEY", "modal-key-fixture")
    monkeypatch.setenv("MODAL_SECRET", "modal-secret-fixture")
    monkeypatch.setenv("MODAL_JSON_SCHEMA", "true")
    seen = {}
    def client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(kwargs=kwargs)
    monkeypatch.setattr(google.adk.models.lite_llm, "LiteLlm", client)
    monkeypatch.setattr(google.adk.agents, "LlmAgent", lambda **kwargs: SimpleNamespace(**kwargs))
    class Runner:
        def __init__(self, **kwargs):
            seen["agent_model"] = kwargs["agent"].model
            seen["output_tokens"] = kwargs["agent"].generate_content_config.max_output_tokens
        async def run_async(self, **kwargs):
            seen["streaming_mode"] = kwargs["run_config"].streaming_mode
            yield SimpleNamespace(usage_metadata=None, content=SimpleNamespace(parts=[SimpleNamespace(text='{"ok":', thought=False)]),
                                  is_final_response=lambda: False)
            yield SimpleNamespace(usage_metadata=None, content=SimpleNamespace(parts=[
                SimpleNamespace(text='private reasoning', thought=True),
                SimpleNamespace(text='{"ok":true}', thought=False)]),
                                  is_final_response=lambda: True)
    monkeypatch.setattr(google.adk.runners, "Runner", Runner)
    roles = ADKRoles(Config(builder_model=model), None, None, None)
    text, usage = asyncio.run(roles._ask(role, "Reply with JSON", {}, Reply, model, 20))
    assert text == '{"ok":true}' and not usage
    assert seen.pop("streaming_mode") == (StreamingMode.SSE if model == QWEN else StreamingMode.NONE)
    assert seen.pop("output_tokens") == (65536 if model == QWEN else 20)
    if model == QWEN:
        assert seen["model"] == "openai/qwen3.8-max-0902"
        assert seen["api_key"] == "qwen-fixture"
        assert seen["extra_body"] == {"enable_thinking": True}
        assert "reasoning_effort" not in seen
    elif model == MODEL:
        assert seen["model"] == "openai/zai-org/GLM-5.3-Flash"
        assert seen["api_key"] == "doubleword-fixture"
        assert seen["api_base"] == "https://api.doubleword.ai/v1"
        assert seen["reasoning_effort"] == ("medium" if role.startswith("synthetic_brief_") else "low")
    elif model.startswith("modal/"):
        assert seen["model"] == "openai/Qwen/fixture"
        assert seen["extra_headers"] == {"Modal-Key": "modal-key-fixture", "Modal-Secret": "modal-secret-fixture"}
    elif "/" in model:
        assert seen["model"] == model and "api_base" not in seen and "api_key" not in seen
    else:
        assert seen == {"agent_model": model}
