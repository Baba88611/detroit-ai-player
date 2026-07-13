from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

import requests


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
    ):
        self.provider = provider
        self.cli_kind = cli_kind
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

    def choose(
        self,
        node_id: str,
        _context: str,
        choices: list[dict[str, str]],
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        raw_text = self._call_api(messages)
        return self._parse_response(raw_text, node_id, choices)

    def token_usage(self) -> dict[str, int]:
        usage = {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }
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

    def _call_api(self, messages: list[dict[str, str]]) -> str:
        if self.provider == "cli":
            return self._call_cli(messages)
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
                return data["choices"][0]["message"]["content"]
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
    def _call_cli(self, messages: list[dict[str, str]]) -> str:
        if self.cli_kind == "claude":
            return self._call_claude_cli(messages)
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

    def _split_cli_messages(self, messages: list[dict[str, str]]) -> tuple[str, str]:
        """把 messages 拆成 system_prompt（走 --system-prompt）和一段拍平的
        对话历史 transcript（走 stdin）。CLI 只吃单段文本，所以用带标签的
        transcript 保留"哪些是场景、哪些是我此前的选择、最后一段是当前场景"。
        标签语言按 system_prompt 是否含中文字符判定，与运行章节保持一致。"""
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
