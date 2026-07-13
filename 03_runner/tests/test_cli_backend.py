from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from api_client import LLMClient  # noqa: E402
from runner import build_llm_client_from_model_registry  # noqa: E402


CLI_VERSION = "2.1.207 (Claude Code)"


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
