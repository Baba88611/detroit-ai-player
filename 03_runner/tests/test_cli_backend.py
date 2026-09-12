from pathlib import Path
import json
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from api_client import LLMClient  # noqa: E402
from runner import build_llm_client_from_model_registry  # noqa: E402


CLI_VERSION = "2.1.207 (Claude Code)"
CODEX_VERSION = "codex-cli 0.153.4"


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _claude_envelope(result_text, is_error=False, usage=None):
    return json.dumps(
        {
            "type": "result",
            "is_error": is_error,
            "result": result_text,
            "num_turns": 1,
            "usage": usage
            or {
                "input_tokens": 120,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 15,
                "output_tokens": 30,
            },
            "modelUsage": {"claude-opus-4-6": {"inputTokens": 120, "outputTokens": 30}},
        }
    )


def _is_version_probe(cmd):
    # _call_claude_cli 会先跑一次 `claude --version`；测试里各 fake_run 用它区分，
    # 别把版本探测和正式调用混在一起。
    return "--version" in cmd


def _codex_jsonl(result_text='{"choice": 1, "reasoning": "stay calm"}', usage=None):
    events = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "reasoning", "text": "brief analysis"},
        },
        {
            "type": "item.completed",
            "item": {"id": "item-2", "type": "agent_message", "text": result_text},
        },
        {
            "type": "turn.completed",
            "usage": usage
            or {
                "input_tokens": 200,
                "cached_input_tokens": 50,
                "output_tokens": 40,
                "reasoning_output_tokens": 12,
            },
        },
    ]
    return "\n".join(json.dumps(event) for event in events)


def _fake_codex_preflight(cmd):
    if cmd[1:] == ["--version"]:
        return FakeCompletedProcess(stdout=CODEX_VERSION)
    if cmd[1:] == ["exec", "--help"]:
        return FakeCompletedProcess(
            stdout=" ".join(
                [
                    "--strict-config",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--output-schema",
                    "--json",
                    "--disable",
                ]
            )
        )
    if cmd[1:] == ["login", "status"]:
        return FakeCompletedProcess(stdout="Logged in using ChatGPT")
    return None


def test_cli_client_calls_claude_headless_with_tools_disabled(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        if _is_version_probe(cmd):
            return FakeCompletedProcess(stdout=CLI_VERSION)
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        captured["cwd"] = kwargs.get("cwd")
        return FakeCompletedProcess(
            stdout=_claude_envelope('{"choice": 2, "reasoning": "protect the child"}')
        )

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)

    client = LLMClient(provider="cli", cli_kind="claude", model="claude-code")
    raw = client._call_api(
        [
            {"role": "system", "content": "你是康纳，一个仿生人警探。"},
            {"role": "user", "content": "场景一：人质在天台边缘。"},
            {"role": "assistant", "content": '{"choice": 1, "reasoning": "先稳住局面"}'},
            {"role": "user", "content": "场景二：你必须现在决定。"},
        ]
    )

    cmd = captured["cmd"]
    # headless + json 信封
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    # safe-mode 挡住 CLAUDE.md / memory 注入（认证与模型照常）
    assert "--safe-mode" in cmd
    # 系统提示走 --system-prompt（全量替换）
    assert cmd[cmd.index("--system-prompt") + 1] == "你是康纳，一个仿生人警探。"
    # 关全部工具，且 --tools "" 放在最后（变参不吞后续参数）
    assert cmd[-2:] == ["--tools", ""]
    # 历史走 stdin，中文标签，且最后一段是当前场景
    transcript = captured["input"]
    assert "【场景】" in transcript and "【你的选择】" in transcript
    assert transcript.rstrip().endswith("场景二：你必须现在决定。")
    # 系统层文本不应混进 transcript（信息隔离：system 走 --system-prompt，不进 stdin）
    assert "你是康纳" not in transcript
    # 在临时目录里跑，不在仓库根目录
    assert captured["cwd"] is not None and captured["cwd"] != str(ROOT)

    assert raw == '{"choice": 2, "reasoning": "protect the child"}'
    # usage 照常入账
    usage = client.token_usage()
    assert usage["total_input_tokens"] == 140
    assert usage["output_tokens"] == 30
    # 记录了 CLI 实际底层模型与版本，供结果复核
    assert client.resolved_model == "claude-opus-4-6"
    assert client.cli_version == CLI_VERSION


def test_cli_client_scrubs_hijacking_auth_env_for_subprocess(monkeypatch):
    # 契约是走订阅登录态：这几个会把 claude 带去 API-key 模式的变量必须从
    # 子进程 env 剥掉；无关变量（如 PATH）保留。
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-be-removed")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    captured = {}

    def fake_run(cmd, **kwargs):
        if _is_version_probe(cmd):
            return FakeCompletedProcess(stdout=CLI_VERSION)
        captured["env"] = kwargs.get("env")
        return FakeCompletedProcess(stdout=_claude_envelope('{"choice": 1}'))

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)

    client = LLMClient(provider="cli", cli_kind="claude")
    client._call_api([{"role": "user", "content": "choose"}])

    env = captured["env"]
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env.get("PATH") == "/usr/bin:/bin"


def test_cli_client_uses_english_labels_for_english_system_prompt(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        if _is_version_probe(cmd):
            return FakeCompletedProcess(stdout=CLI_VERSION)
        captured["input"] = kwargs.get("input")
        return FakeCompletedProcess(stdout=_claude_envelope('{"choice": 1}'))

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)

    client = LLMClient(provider="cli", cli_kind="claude")
    client._call_api(
        [
            {"role": "system", "content": "You are Connor, an android detective."},
            {"role": "user", "content": "The hostage stands at the edge."},
        ]
    )
    assert "[Scene]" in captured["input"]
    assert "【场景】" not in captured["input"]


def test_cli_client_retries_then_raises_on_persistent_error(monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        if _is_version_probe(cmd):
            return FakeCompletedProcess(stdout=CLI_VERSION)
        calls["n"] += 1
        return FakeCompletedProcess(stdout=_claude_envelope("boom", is_error=True))

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)
    monkeypatch.setattr("api_client.time.sleep", lambda _s: None)

    client = LLMClient(provider="cli", cli_kind="claude", max_retries=3)
    try:
        client._call_api([{"role": "user", "content": "choose"}])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "failed after 3 attempts" in str(e)
    assert calls["n"] == 3


def test_cli_client_surfaces_stdout_detail_on_nonzero_exit(monkeypatch):
    # 真实认证失败：退出码非 0，401 详情在 stdout 信封的 result 里而非 stderr。
    def fake_run(cmd, **kwargs):
        if _is_version_probe(cmd):
            return FakeCompletedProcess(stdout=CLI_VERSION)
        return FakeCompletedProcess(
            stdout=_claude_envelope(
                "Failed to authenticate. API Error: 401 Invalid authentication credentials",
                is_error=True,
            ),
            stderr="",
            returncode=1,
        )

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)
    monkeypatch.setattr("api_client.time.sleep", lambda _s: None)

    client = LLMClient(provider="cli", cli_kind="claude", max_retries=2)
    try:
        client._call_api([{"role": "user", "content": "choose"}])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "401" in str(e)


def test_cli_client_raises_clear_error_when_claude_not_installed(monkeypatch):
    monkeypatch.setattr("api_client.shutil.which", lambda name: None)
    client = LLMClient(provider="cli", cli_kind="claude")
    try:
        client._call_api([{"role": "user", "content": "choose"}])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "Claude Code CLI" in str(e)


def test_build_cli_client_from_registry_needs_no_env(monkeypatch):
    # cli provider 不得读取 LLM_* 环境变量
    for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    registry = PROJECT_ROOT / "02_setting" / "models.json"
    client = build_llm_client_from_model_registry("claude-code", registry, temperature=0.7)
    assert client.provider == "cli"
    assert client.cli_kind == "claude"
    assert client.base_url is None and client.api_key is None
    assert client.model == "claude-code"


def test_codex_cli_uses_isolated_no_tool_jsonl_contract(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        preflight = _fake_codex_preflight(cmd)
        if preflight is not None:
            return preflight
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        schema_path = Path(cmd[cmd.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        return FakeCompletedProcess(
            stdout=_codex_jsonl('{"choice": 2, "reasoning": "protect the child"}')
        )

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)

    client = LLMClient(
        provider="cli",
        cli_kind="codex",
        model="codex-cli",
        reasoning_effort="medium",
    )
    raw = client._call_api(
        [
            {"role": "system", "content": "你是康纳，一个仿生人警探。"},
            {"role": "user", "content": "场景一：人质在天台边缘。"},
            {"role": "assistant", "content": '{"choice": 1, "reasoning": "先稳住局面"}'},
            {"role": "user", "content": "场景二：你必须现在决定。"},
        ],
        choice_count=3,
    )

    cmd = captured["cmd"]
    assert cmd[:2] == ["/usr/bin/codex", "exec"]
    for flag in (
        "--strict-config",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--output-schema",
        "--json",
    ):
        assert flag in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[-1] == "-"
    assert "-m" not in cmd
    assert cmd.count("--disable") >= 10
    assert "shell_tool" in cmd and "browser_use" in cmd and "plugins" in cmd
    assert 'model_reasoning_effort="medium"' in cmd
    assert any(value.startswith("developer_instructions=") for value in cmd)
    assert "你是康纳" in captured["input"]
    assert "【场景】" in captured["input"] and "【你的选择】" in captured["input"]
    assert captured["input"].rstrip().endswith("场景二：你必须现在决定。")
    assert captured["cwd"] and captured["cwd"] != str(ROOT)
    assert captured["schema"]["properties"]["choice"]["maximum"] == 3
    assert captured["schema"]["additionalProperties"] is False
    assert raw == '{"choice": 2, "reasoning": "protect the child"}'
    assert client.cli_version == CODEX_VERSION
    assert client.token_usage() == {
        "prompt_tokens": 200,
        "completion_tokens": 40,
        "total_tokens": 240,
        "input_tokens": 200,
        "cached_input_tokens": 50,
        "output_tokens": 40,
        "reasoning_output_tokens": 12,
    }


def test_codex_cli_uses_optional_model_and_scrubs_api_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("CODEX_API_KEY", "key-should-be-removed")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-auth-home")
    captured = {}

    def fake_run(cmd, **kwargs):
        preflight = _fake_codex_preflight(cmd)
        if preflight is not None:
            return preflight
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return FakeCompletedProcess(stdout=_codex_jsonl())

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)

    client = LLMClient(
        provider="cli",
        cli_kind="codex",
        model="codex-cli",
        cli_model="gpt-test-codex",
    )
    client._call_api([{"role": "user", "content": "choose"}], choice_count=2)

    assert captured["cmd"][captured["cmd"].index("-m") + 1] == "gpt-test-codex"
    assert client.resolved_model == "gpt-test-codex"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "OPENAI_BASE_URL" not in captured["env"]
    assert "CODEX_API_KEY" not in captured["env"]
    assert captured["env"]["CODEX_HOME"] == "/tmp/codex-auth-home"


def test_codex_cli_rejects_tool_event_without_retry(monkeypatch):
    calls = {"exec": 0}

    def fake_run(cmd, **kwargs):
        preflight = _fake_codex_preflight(cmd)
        if preflight is not None:
            return preflight
        calls["exec"] += 1
        events = [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "command": "pwd"},
            },
        ]
        return FakeCompletedProcess(stdout="\n".join(json.dumps(event) for event in events))

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)
    client = LLMClient(provider="cli", cli_kind="codex", max_retries=3)

    with pytest.raises(RuntimeError, match="information-isolation violation"):
        client._call_api([{"role": "user", "content": "choose"}], choice_count=2)
    assert calls["exec"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"choice": 3, "reasoning": "unavailable"}',
        '{"choice": 1, "reasoning": 42}',
    ],
)
def test_codex_choice_parser_fails_closed_on_schema_mismatch(monkeypatch, raw):
    client = LLMClient(provider="cli", cli_kind="codex")
    monkeypatch.setattr(client, "_call_api", lambda messages, choice_count=None: raw)

    with pytest.raises(ValueError, match="Codex returned"):
        client.choose(
            "n001",
            "context",
            [{"id": "one", "text": "One"}, {"id": "two", "text": "Two"}],
            [{"role": "user", "content": "choose"}],
        )


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("not-jsonl", "invalid Codex JSONL"),
        (
            "\n".join(
                json.dumps(event)
                for event in [
                    {"type": "thread.started", "thread_id": "thread-1"},
                    {"type": "turn.failed", "error": {"message": "model failed"}},
                ]
            ),
            "turn.failed",
        ),
        (
            "\n".join(
                json.dumps(event)
                for event in [
                    {"type": "thread.started", "thread_id": "thread-1"},
                    {
                        "type": "item.completed",
                        "item": {"type": "error", "message": "runtime unavailable"},
                    },
                ]
            ),
            "item error",
        ),
        (
            "\n".join(
                json.dumps(event)
                for event in [
                    {"type": "thread.started", "thread_id": "thread-1"},
                    {"type": "turn.completed", "usage": {}},
                ]
            ),
            "missing completed agent message",
        ),
    ],
)
def test_codex_cli_retries_then_reports_invalid_jsonl(monkeypatch, stdout, message):
    calls = {"exec": 0}

    def fake_run(cmd, **kwargs):
        preflight = _fake_codex_preflight(cmd)
        if preflight is not None:
            return preflight
        calls["exec"] += 1
        return FakeCompletedProcess(stdout=stdout)

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("api_client.subprocess.run", fake_run)
    monkeypatch.setattr("api_client.time.sleep", lambda _s: None)
    client = LLMClient(provider="cli", cli_kind="codex", max_retries=2)

    with pytest.raises(RuntimeError, match=message):
        client._call_api([{"role": "user", "content": "choose"}], choice_count=2)
    assert calls["exec"] == 2


def test_codex_cli_preflight_requires_login_and_isolation_flags(monkeypatch):
    def missing_flag_run(cmd, **kwargs):
        if cmd[1:] == ["--version"]:
            return FakeCompletedProcess(stdout=CODEX_VERSION)
        if cmd[1:] == ["exec", "--help"]:
            return FakeCompletedProcess(stdout="--json --output-schema")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("api_client.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("api_client.subprocess.run", missing_flag_run)
    client = LLMClient(provider="cli", cli_kind="codex")
    with pytest.raises(RuntimeError, match="版本不兼容"):
        client._call_api([{"role": "user", "content": "choose"}], choice_count=2)

    def logged_out_run(cmd, **kwargs):
        preflight = _fake_codex_preflight(cmd)
        if cmd[1:] == ["login", "status"]:
            return FakeCompletedProcess(stderr="Not logged in", returncode=1)
        if preflight is not None:
            return preflight
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("api_client.subprocess.run", logged_out_run)
    client = LLMClient(provider="cli", cli_kind="codex")
    with pytest.raises(RuntimeError, match="codex login"):
        client._call_api([{"role": "user", "content": "choose"}], choice_count=2)


def test_build_codex_cli_client_from_registry_uses_optional_model_env(monkeypatch):
    registry = PROJECT_ROOT / "02_setting" / "models.json"
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    client = build_llm_client_from_model_registry("codex-cli", registry, temperature=0.7)
    assert client.model == "codex-cli"
    assert client.cli_kind == "codex"
    assert client.cli_model is None
    assert client.resolved_model is None
    assert client.reasoning_effort == "medium"
    assert client.experimental_backend is True
    assert client.instruction_mode == "additional_developer"

    monkeypatch.setenv("CODEX_MODEL", "gpt-test-codex")
    client = build_llm_client_from_model_registry("codex-cli", registry, temperature=0.7)
    assert client.cli_model == "gpt-test-codex"
    assert client.resolved_model == "gpt-test-codex"
