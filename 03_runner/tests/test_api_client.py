from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api_client import LLMClient  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_anthropic_provider_uses_messages_api(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "content": [{"type": "text", "text": '{"choice": 2, "reasoning": "protect the child"}'}],
                "usage": {
                    "input_tokens": 123,
                    "cache_creation_input_tokens": 7,
                    "cache_read_input_tokens": 11,
                    "output_tokens": 45,
                },
            }
        )

    monkeypatch.setattr("api_client.requests.post", fake_post)
    client = LLMClient(
        base_url="https://api.anthropic.com/v1",
        api_key="test-key",
        model="claude-opus-4-6",
        provider="anthropic",
        temperature=0.4,
    )

    raw = client._call_api(
        [
            {"role": "system", "content": "You are Connor."},
            {"role": "user", "content": "Choose."},
        ]
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in captured["headers"]
    assert captured["json"]["system"] == "You are Connor."
    assert captured["json"]["messages"] == [{"role": "user", "content": "Choose."}]
    assert captured["json"]["model"] == "claude-opus-4-6"
    assert captured["json"]["temperature"] == 0.4
    assert captured["json"]["max_tokens"] == 1024
    assert captured["json"]["cache_control"] == {"type": "ephemeral"}
    assert raw == '{"choice": 2, "reasoning": "protect the child"}'
    assert client.token_usage() == {
        "prompt_tokens": 141,
        "completion_tokens": 45,
        "total_tokens": 186,
        "input_tokens": 123,
        "cache_creation_input_tokens": 7,
        "cache_read_input_tokens": 11,
        "output_tokens": 45,
        "total_input_tokens": 141,
    }


def test_openai_compatible_provider_keeps_chat_completions(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse(
            {
                "choices": [{"message": {"content": '{"choice": 1, "reasoning": "calm approach"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }
        )

    monkeypatch.setattr("api_client.requests.post", fake_post)
    client = LLMClient(
        base_url="https://api.openai.test/v1",
        api_key="test-key",
        model="gpt-test",
        provider="openai",
    )

    raw = client._call_api([{"role": "user", "content": "Choose."}])

    assert captured["url"] == "https://api.openai.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["messages"] == [{"role": "user", "content": "Choose."}]
    assert "cache_control" not in captured["json"]
    assert raw == '{"choice": 1, "reasoning": "calm approach"}'
