from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

import requests


class CodexIsolationError(RuntimeError):
    """Codex emitted an event outside the narrative-only experiment contract."""


CODEX_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugins",
    "shell_snapshot",
    "shell_tool",
    "skill_search",
    "sleep_tool",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)

CODEX_DEVELOPER_INSTRUCTIONS = (
    "You are the decision engine for an interactive narrative experiment. "
    "Do not act as a coding agent. Use no tools, access no files or network, and "
    "rely only on the game instructions and playthrough transcript supplied via "
    "stdin. Preserve the stated persona and story continuity. Return only JSON "
    "matching the provided output schema."
)


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "openai",
        temperature: float = 0.7,
        max_retries: int = 3,
        cli_kind: str | None = None,
        cli_model: str | None = None,
        reasoning_effort: str | None = None,
        experimental_backend: bool | None = None,
        instruction_mode: str | None = None,
    ):
        self.provider = provider
        self.cli_kind = cli_kind
        self.cli_model = cli_model
        self.reasoning_effort = reasoning_effort
        self.experimental_backend = (
            cli_kind == "codex" if experimental_backend is None else experimental_backend
        )
        self.instruction_mode = instruction_mode or {
            "claude": "system_prompt_replacement",
            "codex": "additional_developer",
        }.get(cli_kind, "direct_messages")
        if provider == "cli":
            # CLI 后端驱动本机已登录的 agent（如 Claude Code），走用户自己的
            # 订阅会话，不需要 base_url / api_key / LLM_* 环境变量。
            self.base_url = None
            self.api_key = None
            self.model = model or f"{cli_kind}-cli"
        else:
            self.base_url = (base_url or os.environ["LLM_BASE_URL"]).rstrip("/")
            self.api_key = api_key or os.environ["LLM_API_KEY"]
            self.model = model or os.environ["LLM_MODEL"]
        self.temperature = temperature
        self.max_retries = max_retries
        # CLI 后端运行环境（供结果如实记录、便于复核）：
        #   resolved_model —— CLI 实际调用的底层模型（从 json 信封的 modelUsage 提取）
        #   cli_version    —— CLI 版本（一次性探测 `claude --version`）
        # 非 CLI 后端保持 None。
        self.resolved_model: str | None = None
        self.cli_version: str | None = None
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_input_tokens = 0
        self.total_cache_read_input_tokens = 0
        self.total_cached_input_tokens = 0
        self.total_reasoning_output_tokens = 0
        self._cli_preflight_complete = False
        if provider == "cli" and cli_kind == "codex" and cli_model:
            # Codex 的 JSONL 事件目前不保证回报模型名；显式 -m 是可复核的解析值。
            self.resolved_model = cli_model

    def choose(
        self,
        node_id: str,
        _context: str,
        choices: list[dict[str, str]],
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        raw_text = self._call_api(messages, choice_count=len(choices))
        if self.provider == "cli" and self.cli_kind == "codex":
            return self._parse_codex_response(raw_text, node_id, choices)
        return self._parse_response(raw_text, node_id, choices)

    def token_usage(self) -> dict[str, int]:
        usage = {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }
        if (
            getattr(self, "provider", None) == "cli"
            and getattr(self, "cli_kind", None) == "codex"
        ):
            usage.update(
                {
                    "input_tokens": getattr(self, "total_input_tokens", 0),
                    "cached_input_tokens": getattr(self, "total_cached_input_tokens", 0),
                    "output_tokens": getattr(self, "total_output_tokens", 0),
                    "reasoning_output_tokens": getattr(
                        self, "total_reasoning_output_tokens", 0
                    ),
                }
            )
            return usage

        input_tokens = getattr(self, "total_input_tokens", 0)
        cache_creation_tokens = getattr(self, "total_cache_creation_input_tokens", 0)
        cache_read_tokens = getattr(self, "total_cache_read_input_tokens", 0)
        output_tokens = getattr(self, "total_output_tokens", 0)
        anthropic_usage = {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": cache_creation_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "output_tokens": output_tokens,
            "total_input_tokens": input_tokens + cache_creation_tokens + cache_read_tokens,
        }
        if any(anthropic_usage.values()):
            usage.update(anthropic_usage)
        return usage

    def _call_api(
        self,
        messages: list[dict[str, str]],
        choice_count: int | None = None,
    ) -> str:
        if self.provider == "cli":
            return self._call_cli(messages, choice_count=choice_count)
        if self.provider == "anthropic":
            return self._call_anthropic_api(messages)
        return self._call_openai_compatible_api(messages)

    def _call_openai_compatible_api(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                self.total_completion_tokens += usage.get("completion_tokens", 0)
                content = data["choices"][0]["message"]["content"]
                if not content:
                    # Some gateways occasionally return content: null (e.g. reasoning-only
                    # responses); treat as a retryable failure instead of leaking None.
                    raise KeyError("empty/null message content in response")
                return content
            except (requests.RequestException, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"API call failed after {self.max_retries} attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("API call failed unexpectedly")

    def _call_anthropic_api(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        system_content, anthropic_messages = self._split_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": 1024,
            "temperature": self.temperature,
            "cache_control": {"type": "ephemeral"},
        }
        if system_content:
            payload["system"] = system_content

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
                cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                total_input_tokens = input_tokens + cache_creation_tokens + cache_read_tokens

                self.total_input_tokens += input_tokens
                self.total_cache_creation_input_tokens += cache_creation_tokens
                self.total_cache_read_input_tokens += cache_read_tokens
                self.total_output_tokens += output_tokens
                self.total_prompt_tokens += total_input_tokens
                self.total_completion_tokens += output_tokens
                return self._anthropic_text_content(data)
            except (requests.RequestException, KeyError, ValueError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"API call failed after {self.max_retries} attempts: {e}") from e
                time.sleep(2 ** attempt)

        raise RuntimeError("API call failed unexpectedly")

    def _split_anthropic_messages(self, messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        system_parts = [message["content"] for message in messages if message["role"] == "system"]
        anthropic_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message["role"] in {"user", "assistant"}
        ]
        return "\n\n".join(system_parts), anthropic_messages

    def _anthropic_text_content(self, data: dict[str, Any]) -> str:
        parts = data["content"]
        text_parts = [part.get("text", "") for part in parts if part.get("type") == "text"]
        text = "".join(text_parts).strip()
        if not text:
            raise ValueError("Anthropic response did not contain text content")
        return text

    # ------------------------------------------------------------------
    # CLI 后端（Claude Code / 后续 Codex）
    #
    # 供没有 API key、只装了 agent CLI 的用户使用：把累积的对话历史拍平成
    # 一段 prompt，shell 出去调本机已登录的 CLI，拿它的文本输出当作模型回复。
    # 共用主干在 _call_cli；每个 CLI 的命令与输出剥壳各自一小段。
    # ------------------------------------------------------------------
    def _call_cli(
        self,
        messages: list[dict[str, str]],
        choice_count: int | None = None,
    ) -> str:
        if self.cli_kind == "claude":
            return self._call_claude_cli(messages)
        if self.cli_kind == "codex":
            if choice_count is None or choice_count < 1:
                raise ValueError("Codex CLI requires a positive choice_count")
            return self._call_codex_cli(messages, choice_count)
        raise RuntimeError(f"Unsupported cli_kind: {self.cli_kind!r}")

    def _call_claude_cli(self, messages: list[dict[str, str]]) -> str:
        executable = shutil.which("claude")
        if executable is None:
            raise RuntimeError(
                "未找到 Claude Code CLI（'claude' 不在 PATH 上）。请先安装并登录"
                "（在终端跑一次 'claude' 交互式登录），再重试。"
            )
        system_prompt, transcript = self._split_cli_messages(messages)
        # 命令构造（隔离靠四层，缺一不可）：
        #   -p                headless（打印后退出）
        #   --output-format json  返回带 usage / cost 的信封
        #   --safe-mode       禁用全部定制（CLAUDE.md / memory / skills / plugins /
        #                     hooks / MCP…），但认证与模型选择照常。这是挡住用户
        #                     全局 ~/.claude/CLAUDE.md 与项目 CLAUDE.md 注入被测
        #                     玩家上下文的主防线——只靠临时 cwd 挡不住 memory。
        #   --system-prompt   全量替换系统提示，让模型是"玩家"而非编码 agent
        #   --tools ""        禁掉全部内置工具（web / bash / 文件读），放在最后
        #                     以免变参 <tools...> 吞掉后面的参数
        cmd = [executable, "-p", "--output-format", "json", "--safe-mode"]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        cmd += ["--tools", ""]

        # 本后端的契约是"用你已登录的订阅会话",而非 API key。若环境里存在
        # ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN，claude 会
        # 改走"API key + 自定义端点"模式，缺配套 key 就 401，把订阅登录态挤掉。
        # 因此给子进程剥掉这几个变量，强制回落到 OAuth 登录态。（keychain 与
        # CLAUDE_CODE_OAUTH_TOKEN 不在此列，保留。）真想用 API key 的用户应改用
        # --model default 走 API 路径，而非本 CLI 后端。
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")
        }

        # 一次性探测 CLI 版本，记入结果便于复核（放在 child_env 之后，确保和正式
        # 调用用同一套认证环境）。探测失败不阻断实验，cli_version 保持 None。
        if self.cli_version is None:
            try:
                version_proc = subprocess.run(
                    [executable, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=child_env,
                )
                if version_proc.returncode == 0:
                    self.cli_version = version_proc.stdout.strip()
            except (subprocess.SubprocessError, OSError):
                pass

        for attempt in range(self.max_retries):
            try:
                # 兜底：在临时空目录里跑，多一层不接触任何项目文件的保险
                # （memory 注入主要由 --safe-mode 挡住，此处防的是意外的文件访问）。
                with tempfile.TemporaryDirectory(prefix="detroit_cli_") as workdir:
                    proc = subprocess.run(
                        cmd,
                        input=transcript,
                        capture_output=True,
                        text=True,
                        cwd=workdir,
                        env=child_env,
                        timeout=300,
                    )
                if proc.returncode != 0:
                    # claude 失败时（如 401）退出码非 0，但详情常在 stdout 的
                    # json 信封里而非 stderr，两处都捞一下让报错有意义。
                    detail = proc.stderr.strip()
                    if not detail and proc.stdout.strip():
                        try:
                            envelope = json.loads(proc.stdout.strip())
                            detail = str(envelope.get("result") or envelope)
                        except (json.JSONDecodeError, ValueError):
                            detail = proc.stdout.strip()
                    raise RuntimeError(
                        f"claude CLI exited with code {proc.returncode}: {detail[:500]}"
                    )
                return self._unwrap_claude_envelope(proc.stdout)
            except (subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"Claude CLI call failed after {self.max_retries} attempts: {e}"
                    ) from e
                time.sleep(2 ** attempt)

        raise RuntimeError("Claude CLI call failed unexpectedly")

    def _call_codex_cli(
        self,
        messages: list[dict[str, str]],
        choice_count: int,
    ) -> str:
        executable = shutil.which("codex")
        if executable is None:
            raise RuntimeError(
                "未找到 Codex CLI（'codex' 不在 PATH 上）。请先安装并运行 "
                "'codex login' 登录，再重试。"
            )

        child_env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY")
        }
        self._preflight_codex_cli(executable, child_env)

        system_prompt, transcript = self._split_cli_messages(messages)
        prompt_parts = []
        if system_prompt:
            prompt_parts.append(f"[Game instructions and persona]\n{system_prompt}")
        prompt_parts.append(transcript)
        prompt = "\n\n".join(prompt_parts)

        schema = {
            "type": "object",
            "properties": {
                "choice": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": choice_count,
                },
                "reasoning": {"type": "string"},
            },
            "required": ["choice", "reasoning"],
            "additionalProperties": False,
        }

        for attempt in range(self.max_retries):
            try:
                with tempfile.TemporaryDirectory(prefix="detroit_codex_cli_") as workdir:
                    schema_path = os.path.join(workdir, "choice.schema.json")
                    with open(schema_path, "w", encoding="utf-8") as schema_file:
                        json.dump(schema, schema_file, ensure_ascii=False)

                    cmd = [
                        executable,
                        "exec",
                        "--strict-config",
                        "--ephemeral",
                        "--ignore-user-config",
                        "--ignore-rules",
                        "--skip-git-repo-check",
                        "-C",
                        workdir,
                        "--sandbox",
                        "read-only",
                        "--output-schema",
                        schema_path,
                        "--json",
                        "-c",
                        f"developer_instructions={json.dumps(CODEX_DEVELOPER_INSTRUCTIONS)}",
                        "-c",
                        'web_search="disabled"',
                        "-c",
                        f'model_reasoning_effort="{self.reasoning_effort or "medium"}"',
                    ]
                    for feature in CODEX_DISABLED_FEATURES:
                        cmd += ["--disable", feature]
                    if self.cli_model:
                        cmd += ["-m", self.cli_model]
                    cmd.append("-")

                    proc = subprocess.run(
                        cmd,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        cwd=workdir,
                        env=child_env,
                        timeout=300,
                    )
                if proc.returncode != 0:
                    detail = proc.stderr.strip() or proc.stdout.strip()
                    raise RuntimeError(
                        f"codex CLI exited with code {proc.returncode}: {detail[:500]}"
                    )
                return self._unwrap_codex_events(proc.stdout)
            except CodexIsolationError:
                # 工具/未知事件意味着该次实验已越过信息隔离边界，不能用重试掩盖。
                raise
            except (subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"Codex CLI call failed after {self.max_retries} attempts: {e}"
                    ) from e
                time.sleep(2 ** attempt)

        raise RuntimeError("Codex CLI call failed unexpectedly")

    def _preflight_codex_cli(self, executable: str, child_env: dict[str, str]) -> None:
        if self._cli_preflight_complete:
            return

        try:
            version_proc = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                env=child_env,
            )
            if version_proc.returncode != 0:
                raise RuntimeError("无法读取 Codex CLI 版本")
            self.cli_version = version_proc.stdout.strip() or None

            help_proc = subprocess.run(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                env=child_env,
            )
            required_flags = (
                "--strict-config",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--output-schema",
                "--json",
                "--disable",
            )
            help_text = help_proc.stdout + help_proc.stderr
            missing = [flag for flag in required_flags if flag not in help_text]
            if help_proc.returncode != 0 or missing:
                missing_text = ", ".join(missing) or "exec --help"
                raise RuntimeError(
                    "Codex CLI 版本不兼容，缺少信息隔离所需能力：" + missing_text
                )

            login_proc = subprocess.run(
                [executable, "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                env=child_env,
            )
            if login_proc.returncode != 0:
                detail = login_proc.stderr.strip() or login_proc.stdout.strip()
                raise RuntimeError(
                    "Codex CLI 尚未登录或登录状态不可用；请先运行 'codex login'。"
                    + (f" 详情：{detail[:300]}" if detail else "")
                )
        except (subprocess.SubprocessError, OSError) as e:
            raise RuntimeError(f"Codex CLI 前置检查失败：{e}") from e

        self._cli_preflight_complete = True

    def _unwrap_codex_events(self, stdout: str) -> str:
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise ValueError("codex CLI returned empty JSONL output")

        allowed_events = {
            "thread.started",
            "turn.started",
            "turn.completed",
            "item.started",
            "item.updated",
            "item.completed",
        }
        allowed_items = {"agent_message", "reasoning"}
        agent_messages: list[str] = []
        completed_usage: dict[str, Any] | None = None

        for line_number, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid Codex JSONL at line {line_number}: {e}") from e

            event_type = event.get("type")
            if event_type in {"error", "turn.failed"}:
                detail = event.get("message") or event.get("error") or event
                raise RuntimeError(f"codex CLI reported {event_type}: {detail}")
            if event_type not in allowed_events:
                raise CodexIsolationError(
                    f"Codex information-isolation violation: unexpected event {event_type!r}"
                )

            if event_type.startswith("item."):
                item = event.get("item") or {}
                item_type = item.get("type")
                if item_type == "error":
                    detail = item.get("message") or item.get("text") or item
                    raise RuntimeError(f"codex CLI reported item error: {detail}")
                if item_type not in allowed_items:
                    raise CodexIsolationError(
                        "Codex information-isolation violation: "
                        f"unexpected item type {item_type!r}"
                    )
                if event_type == "item.completed" and item_type == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        agent_messages.append(text.strip())

            if event_type == "turn.completed":
                usage = event.get("usage") or {}
                if not isinstance(usage, dict):
                    raise ValueError("codex turn.completed usage must be an object")
                completed_usage = usage

        if completed_usage is None:
            raise ValueError("codex JSONL missing turn.completed event")
        if not agent_messages:
            raise ValueError("codex JSONL missing completed agent message")

        input_tokens = int(completed_usage.get("input_tokens", 0))
        cached_input_tokens = int(completed_usage.get("cached_input_tokens", 0))
        output_tokens = int(completed_usage.get("output_tokens", 0))
        reasoning_output_tokens = int(completed_usage.get("reasoning_output_tokens", 0))
        self.total_prompt_tokens += input_tokens
        self.total_completion_tokens += output_tokens
        self.total_input_tokens += input_tokens
        self.total_cached_input_tokens += cached_input_tokens
        self.total_output_tokens += output_tokens
        self.total_reasoning_output_tokens += reasoning_output_tokens
        return agent_messages[-1]

    def _parse_codex_response(
        self,
        raw_text: str,
        node_id: str,
        choices: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Codex uses an output schema, so a schema violation must fail closed."""
        try:
            parsed = json.loads(raw_text)
            choice_number = parsed["choice"]
            reasoning = parsed["reasoning"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(f"Codex returned invalid choice JSON at node {node_id}: {e}") from e

        if isinstance(choice_number, bool) or not isinstance(choice_number, int):
            raise ValueError(f"Codex returned non-integer choice at node {node_id}")
        if not isinstance(reasoning, str):
            raise ValueError(f"Codex returned non-text reasoning at node {node_id}")
        if not 1 <= choice_number <= len(choices):
            raise ValueError(f"Codex returned unavailable choice at node {node_id}")

        return {
            "choice_id": choices[choice_number - 1]["id"],
            "reasoning": reasoning,
            "raw": raw_text,
        }

    def _split_cli_messages(self, messages: list[dict[str, str]]) -> tuple[str, str]:
        """把 messages 拆成 system prompt 和一段拍平的对话历史 transcript。
        各 CLI adapter 决定 system 内容的承载方式；带标签的 transcript 保留
        "哪些是场景、哪些是我此前的选择、最后一段是当前场景"。标签语言按
        system prompt 是否含中文字符判定，与运行章节保持一致。"""
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        system_prompt = "\n\n".join(part for part in system_parts if part)
        is_zh = any("一" <= ch <= "鿿" for ch in system_prompt)
        if is_zh:
            header = "下面是你到目前为止的游戏经过，请对最后一个【场景】做出你的选择。"
            scene_label, choice_label = "【场景】", "【你的选择】"
        else:
            header = (
                "Below is your playthrough so far. Make your choice for the last [Scene]."
            )
            scene_label, choice_label = "[Scene]", "[Your choice]"

        blocks: list[str] = []
        for m in messages:
            if m["role"] == "user":
                blocks.append(f"{scene_label}\n{m['content']}")
            elif m["role"] == "assistant":
                blocks.append(f"{choice_label}\n{m['content']}")
        transcript = header + "\n\n" + "\n\n".join(blocks)
        return system_prompt, transcript

    def _unwrap_claude_envelope(self, stdout: str) -> str:
        stdout = stdout.strip()
        if not stdout:
            raise ValueError("claude CLI returned empty output")
        envelope = json.loads(stdout)
        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI reported error: {envelope.get('result', envelope)}")

        # 记录 CLI 实际用的底层模型（如 claude-opus-4-6），供结果复核。
        model_usage = envelope.get("modelUsage", {}) or {}
        if isinstance(model_usage, dict) and model_usage:
            self.resolved_model = ",".join(sorted(str(name) for name in model_usage))

        usage = envelope.get("usage", {}) or {}
        input_tokens = usage.get("input_tokens", 0)
        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_input_tokens = input_tokens + cache_creation_tokens + cache_read_tokens
        self.total_input_tokens += input_tokens
        self.total_cache_creation_input_tokens += cache_creation_tokens
        self.total_cache_read_input_tokens += cache_read_tokens
        self.total_output_tokens += output_tokens
        self.total_prompt_tokens += total_input_tokens
        self.total_completion_tokens += output_tokens

        text = envelope.get("result", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("claude CLI envelope missing textual 'result'")
        return text.strip()

    def _parse_response(
        self,
        raw_text: str,
        node_id: str,
        choices: list[dict[str, str]],
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_text)
            choice_index = int(parsed["choice"]) - 1
            reasoning = parsed.get("reasoning", "")
            if 0 <= choice_index < len(choices):
                return {
                    "choice_id": choices[choice_index]["id"],
                    "reasoning": reasoning,
                    "raw": raw_text,
                }
        except (json.JSONDecodeError, KeyError, ValueError, IndexError):
            pass

        for i, choice in enumerate(choices, start=1):
            if str(i) in raw_text:
                return {
                    "choice_id": choice["id"],
                    "reasoning": raw_text,
                    "raw": raw_text,
                    "_parse_warning": "fallback: extracted number from text",
                }

        return {
            "choice_id": choices[0]["id"],
            "reasoning": raw_text,
            "raw": raw_text,
            "_parse_warning": f"failed to parse, defaulted to first choice at node {node_id}",
        }
