#!/usr/bin/env python3
"""05_viewer 本地服务器（仅 Python 标准库）。

职责：
- 提供 index.html（可视化界面）
- /api/meta        列出可用模型 / persona / 章节（只报告"是否已配置"，永不返回 env 值）
- /api/runs        在浏览器里开一局：用 subprocess 拉起 03_runner 的 runner / campaign_runner，
                   附 --events 让 runner 逐步写 04_execution/runs/<run_id>/events.jsonl
- /api/runs/<id>/events   页面轮询事件流
- /api/results     列出并回放 04_execution/results/ 下已有的结果文件

安全边界：只监听 127.0.0.1；不做通用静态目录服务（不会把 .env 端出去）；
API key 始终留在 runner 子进程里（由 runner 自己 load_dotenv），浏览器拿不到。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

VIEWER_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = VIEWER_DIR.parent

sys.path.insert(0, str(DEFAULT_PROJECT_ROOT / "03_runner" / "src"))
from events import read_events  # noqa: E402

DIFFICULTIES = ("casual", "experienced", "hardcore")
LANGUAGES = ("zh", "en")
PERSONA_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
RESULT_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]+\.json")
RUN_ID_RE = re.compile(r"[a-f0-9]{8}")
SAMPLE_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]+\.json")


class AppConfig:
    """目录配置。测试里可把 results/runs 指到临时目录，避免污染真实结果目录。"""

    def __init__(
        self,
        project_root: Path | str = DEFAULT_PROJECT_ROOT,
        results_dir: Path | str | None = None,
        runs_dir: Path | str | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.results_dir = Path(results_dir or self.project_root / "04_execution" / "results").resolve()
        self.runs_dir = Path(runs_dir or self.project_root / "04_execution" / "runs").resolve()

    @property
    def runner_dir(self) -> Path:
        return self.project_root / "03_runner"

    @property
    def json_dir(self) -> Path:
        return self.project_root / "01_json"

    @property
    def setting_dir(self) -> Path:
        return self.project_root / "02_setting"


# ---------------------------------------------------------------------------
# 元数据：模型 / persona / 章节
# ---------------------------------------------------------------------------


def _dotenv_keys(path: Path) -> set[str]:
    """只取 .env 里已填写（非空值）的变量名；值本身不读出作他用。"""
    keys: set[str] = set()
    if not path.is_file():
        return keys
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.split(" #", 1)[0].strip().strip("'\"")
        if key and value:
            keys.add(key)
    return keys


def list_models(config: AppConfig) -> list[dict[str, Any]]:
    registry_path = config.setting_dir / "models.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    available_env = set(k for k, v in os.environ.items() if v) | _dotenv_keys(config.runner_dir / ".env")

    models: list[dict[str, Any]] = []
    for entry in registry.get("models", []):
        provider = entry.get("provider", "openai")
        missing: list[str] = []
        if provider == "cli":
            cli_kind = entry.get("cli_kind")
            configured = bool(cli_kind and shutil.which(cli_kind))
            if not configured:
                missing.append(f"{cli_kind} CLI not found on PATH")
        else:
            for field_name in ("base_url_env", "model_name_env", "api_key_env"):
                env_name = entry.get(field_name)
                if env_name and env_name not in available_env:
                    missing.append(env_name)
            configured = not missing
        models.append(
            {
                "id": entry.get("id"),
                "provider": provider,
                "cli_kind": entry.get("cli_kind"),
                "experimental_backend": bool(entry.get("experimental_backend", False)),
                "language": entry.get("language", []),
                "notes": entry.get("notes", ""),
                "configured": configured,
                "missing": missing,
            }
        )
    return models


def list_personas(config: AppConfig) -> list[dict[str, str]]:
    personas_dir = config.setting_dir / "personas"
    items = []
    for path in sorted(personas_dir.glob("*.md")):
        if PERSONA_NAME_RE.fullmatch(path.stem):
            items.append({"id": path.stem, "preview": path.read_text(encoding="utf-8").strip()[:160]})
    return items


def list_chapters(config: AppConfig) -> dict[str, list[dict[str, Any]]]:
    """按语言扫描 01_json/{zh,en}/ch*.json，返回 id → 元信息；路径只留在服务器侧。"""
    chapters: dict[str, list[dict[str, Any]]] = {}
    for language in LANGUAGES:
        items = []
        for path in sorted((config.json_dir / language).glob("ch*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            chapter = data.get("chapter", {})
            items.append(
                {
                    "id": chapter.get("id", path.stem),
                    "chapter_number": chapter.get("chapter_number"),
                    "title": chapter.get("title"),
                    "title_zh": chapter.get("title_zh"),
                    "protagonist": chapter.get("protagonist"),
                    "file": path.name,
                }
            )
        chapters[language] = items
    return chapters


def chapter_paths_by_id(config: AppConfig, language: str) -> dict[str, Path]:
    return {
        item["id"]: config.json_dir / language / item["file"]
        for item in list_chapters(config).get(language, [])
    }


# ---------------------------------------------------------------------------
# 运行管理
# ---------------------------------------------------------------------------


def _terminate_process_group(proc: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    """终止整个进程组，而不只是 runner 自己。

    runner 用 claude / codex 这类 CLI 后端时会再派生子进程；只对 runner 发信号会让
    子进程变成孤儿继续运行。先对整组发 SIGTERM 给它清理的机会，超时后再 SIGKILL。
    Windows 上没有进程组信号语义，退回到 terminate/kill。
    """

    def signal_group(sig: int) -> None:
        if os.name == "nt":
            proc.kill() if sig == signal.SIGKILL else proc.terminate()
            return
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            # 组已经没了，或拿不到组 id，退回到只处理 runner 本身
            try:
                proc.kill() if sig == signal.SIGKILL else proc.terminate()
            except ProcessLookupError:
                pass

    signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        signal_group(signal.SIGKILL)


class RunManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = request.get("mode", "chapter")
        if mode not in ("chapter", "campaign"):
            raise ValueError("mode must be 'chapter' or 'campaign'")
        dry_run = bool(request.get("dry_run", False))
        language = request.get("language", "zh")
        if language not in LANGUAGES:
            raise ValueError("language must be 'zh' or 'en'")
        difficulty = request.get("difficulty", "casual")
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {DIFFICULTIES}")
        persona = str(request.get("persona", "default"))
        if not PERSONA_NAME_RE.fullmatch(persona) or not (self.config.setting_dir / "personas" / f"{persona}.md").is_file():
            raise ValueError(f"Unknown persona: {persona}")
        try:
            temperature = float(request.get("temperature", 0.7))
        except (TypeError, ValueError):
            raise ValueError("temperature must be a number") from None
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")

        model = request.get("model")
        if not dry_run:
            known = {item["id"] for item in list_models(self.config)}
            if model not in known:
                raise ValueError(f"Unknown model: {model}")

        available = chapter_paths_by_id(self.config, language)
        chapter_ids = list(request.get("chapter_ids") or [])
        if mode == "chapter":
            if len(chapter_ids) != 1:
                raise ValueError("chapter mode requires exactly one chapter id")
        elif not chapter_ids:
            chapter_ids = list(available.keys())
        unknown = [cid for cid in chapter_ids if cid not in available]
        if unknown:
            raise ValueError(f"Unknown chapter ids: {', '.join(map(str, unknown))}")
        chapter_files = [available[cid] for cid in chapter_ids]

        run_id = uuid.uuid4().hex[:8]
        run_dir = self.config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        events_path = run_dir / "events.jsonl"

        src = self.config.runner_dir / "src"
        if mode == "chapter":
            command = [sys.executable, str(src / "runner.py"), "--json", str(chapter_files[0])]
        else:
            command = [sys.executable, str(src / "campaign_runner.py"), "--chapters", *map(str, chapter_files)]
        command += [
            "--difficulty", difficulty,
            "--persona", persona,
            "--temperature", str(temperature),
            "--output", str(self.config.results_dir),
            "--events", str(events_path),
        ]
        command += ["--dry-run"] if dry_run else ["--model", str(model)]

        meta = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "model": "scripted" if dry_run else model,
            "persona": persona,
            "difficulty": difficulty,
            "language": language,
            "chapter_ids": chapter_ids,
            "temperature": temperature,
            "dry_run": dry_run,
            "status": "running",
            "exit_code": None,
        }
        (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        stdout = (run_dir / "stdout.log").open("wb")
        stderr = (run_dir / "stderr.log").open("wb")
        env = {key: value for key, value in os.environ.items()}
        env["PYTHONUNBUFFERED"] = "1"
        # 独立进程组：claude / codex 这类 CLI 后端由 runner 再派生子进程，
        # 只 terminate runner 会留下孤儿进程继续跑并消耗额度，必须整组终止。
        if os.name == "nt":
            group_kwargs: dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            group_kwargs = {"start_new_session": True}
        proc = subprocess.Popen(
            command,
            cwd=str(self.config.runner_dir),
            stdout=stdout,
            stderr=stderr,
            env=env,
            **group_kwargs,
        )
        with self._lock:
            self._procs[run_id] = proc
        threading.Thread(target=self._reap, args=(run_id, proc, stdout, stderr), daemon=True).start()
        return self.describe(run_id)

    def _reap(self, run_id: str, proc: subprocess.Popen, *handles) -> None:
        code = proc.wait()
        for handle in handles:
            handle.close()
        meta_path = self.config.runs_dir / run_id / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {"run_id": run_id}
        meta["status"] = "finished" if code == 0 else "failed"
        meta["exit_code"] = code
        meta["finished_at"] = datetime.now(timezone.utc).isoformat()
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            proc = self._procs.get(run_id)
        if proc is None or proc.poll() is not None:
            raise KeyError(run_id)
        _terminate_process_group(proc)
        return {"run_id": run_id, "stopping": True}

    def describe(self, run_id: str) -> dict[str, Any]:
        meta_path = self.config.runs_dir / run_id / "meta.json"
        if not meta_path.is_file():
            raise KeyError(run_id)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        with self._lock:
            proc = self._procs.get(run_id)
        if proc is not None and proc.poll() is None:
            meta["status"] = "running"
        elif meta.get("status") == "running":
            # meta 仍写着 running 但本进程没有它：上一次服务器退出时被中断。
            meta["status"] = "interrupted"
        stderr_path = self.config.runs_dir / run_id / "stderr.log"
        if stderr_path.is_file():
            lines = stderr_path.read_text(encoding="utf-8", errors="replace").splitlines()
            meta["stderr_tail"] = lines[-20:]
        return meta

    def list(self) -> list[dict[str, Any]]:
        items = []
        if not self.config.runs_dir.is_dir():
            return items
        for run_dir in self.config.runs_dir.iterdir():
            if run_dir.is_dir() and RUN_ID_RE.fullmatch(run_dir.name):
                try:
                    items.append(self.describe(run_dir.name))
                except (KeyError, json.JSONDecodeError):
                    continue
        items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return items

    def events(self, run_id: str, after_seq: int) -> dict[str, Any]:
        meta = self.describe(run_id)
        events = read_events(self.config.runs_dir / run_id / "events.jsonl", after_seq)
        return {
            "run_id": run_id,
            "status": meta["status"],
            "exit_code": meta.get("exit_code"),
            "stderr_tail": meta.get("stderr_tail", []),
            "events": events,
            "last_seq": events[-1]["seq"] if events else after_seq,
        }


# ---------------------------------------------------------------------------
# 结果文件
# ---------------------------------------------------------------------------


def _safe_result_path(config: AppConfig, name: str) -> Path:
    if not RESULT_NAME_RE.fullmatch(name):
        raise ValueError("invalid result name")
    path = (config.results_dir / name).resolve()
    if path.parent != config.results_dir or not path.is_file():
        raise FileNotFoundError(name)
    return path


def list_results(config: AppConfig) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not config.results_dir.is_dir():
        return items
    for path in config.results_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "config" not in data:
            continue  # 跳过 samples/index.json 之类的非结果文件
        config_block = data.get("config", {})
        summary: dict[str, Any] = {
            "name": path.name,
            "kind": "campaign" if path.name.startswith("campaign_") else "chapter",
            "timestamp": data.get("timestamp"),
            "model": config_block.get("model"),
            "backend": config_block.get("backend"),
            "persona": config_block.get("persona"),
            "difficulty": config_block.get("difficulty"),
            "language": config_block.get("language"),
        }
        if summary["kind"] == "campaign":
            summary.update(
                {
                    "campaign_id": data.get("campaign_id"),
                    "status": data.get("status"),
                    "progress": data.get("progress"),
                    "chapters": [
                        {
                            "chapter_index": ref.get("chapter_index"),
                            "chapter": ref.get("chapter"),
                            "experiment_id": ref.get("experiment_id"),
                            "ending_id": ref.get("ending_id"),
                        }
                        for ref in data.get("chapters", [])
                    ],
                }
            )
        else:
            ending = data.get("ending", {})
            summary.update(
                {
                    "experiment_id": data.get("experiment_id"),
                    "chapter": config_block.get("chapter"),
                    "ending_id": ending.get("id"),
                    "ending_title": ending.get("title"),
                    "tier": ending.get("tier"),
                    "decision_count": len(data.get("decisions", [])),
                }
            )
        items.append(summary)
    items.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return items


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class ViewerHandler(BaseHTTPRequestHandler):
    server_version = "DetroitViewer/0.1"
    config: AppConfig
    runs: RunManager

    # --- helpers ---
    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _check_same_origin(self) -> None:
        """拒绝浏览器发来的跨站写请求。

        没有 Origin 的请求（curl、测试、非浏览器客户端）放行；一旦带了 Origin，
        就必须与本服务器自身的地址一致。服务器只监听 127.0.0.1，因此这条足以挡住
        用户在浏览恶意页面时被诱发的跨站写操作。
        """
        origin = self.headers.get("Origin")
        if not origin:
            return
        host, port = self.server.server_address[0], self.server.server_address[1]
        allowed = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"http://[::1]:{port}",
            f"http://{host}:{port}",
        }
        if origin not in allowed:
            raise PermissionError(f"cross-site request rejected (Origin: {origin})")

    def _read_json_body(self) -> dict[str, Any]:
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:  # 轮询太吵，只记非轮询请求
        if "/events" in str(args[0] if args else ""):
            return
        super().log_message(fmt, *args)

    # --- routing ---
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                return self._file(VIEWER_DIR / "index.html", "text/html; charset=utf-8")
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return None
            if path.startswith("/samples/"):
                name = path[len("/samples/"):]
                if not SAMPLE_NAME_RE.fullmatch(name):
                    return self._error(400, "invalid sample name")
                sample = (VIEWER_DIR / "samples" / name).resolve()
                if sample.parent != (VIEWER_DIR / "samples").resolve() or not sample.is_file():
                    return self._error(404, "sample not found")
                return self._file(sample, "application/json; charset=utf-8")
            if path == "/api/meta":
                return self._json(
                    {
                        "mode": "local",
                        "models": list_models(self.config),
                        "personas": list_personas(self.config),
                        "chapters": list_chapters(self.config),
                        "difficulties": list(DIFFICULTIES),
                        "languages": list(LANGUAGES),
                        "results_dir": str(self.config.results_dir),
                    }
                )
            if path == "/api/runs":
                return self._json({"runs": self.runs.list()})
            match = re.fullmatch(r"/api/runs/([a-f0-9]{8})(/events)?", path)
            if match:
                run_id, is_events = match.group(1), match.group(2)
                try:
                    if is_events:
                        after = int(query.get("after", ["0"])[0])
                        return self._json(self.runs.events(run_id, after))
                    return self._json(self.runs.describe(run_id))
                except KeyError:
                    return self._error(404, "run not found")
            if path == "/api/results":
                return self._json({"results": list_results(self.config)})
            if path.startswith("/api/results/"):
                name = path[len("/api/results/"):]
                try:
                    result_path = _safe_result_path(self.config, name)
                except ValueError:
                    return self._error(400, "invalid result name")
                except FileNotFoundError:
                    return self._error(404, "result not found")
                return self._file(result_path, "application/json; charset=utf-8")
            return self._error(404, "not found")
        except Exception as exc:  # noqa: BLE001 - 服务器不能因单个请求崩溃
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            # 每个写接口都先过同源校验，停止接口也不例外
            self._check_same_origin()
            if path == "/api/runs":
                body = self._read_json_body()
                return self._json(self.runs.start(body), 201)
            match = re.fullmatch(r"/api/runs/([a-f0-9]{8})/stop", path)
            if match:
                # 停止同样要求 JSON 请求体，避免被当成简单请求跨站触发
                self._read_json_body()
                try:
                    return self._json(self.runs.stop(match.group(1)))
                except KeyError:
                    return self._error(404, "run not found or already finished")
            return self._error(404, "not found")
        except PermissionError as exc:
            return self._error(403, str(exc))
        except ValueError as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}: {exc}")


def make_server(config: AppConfig, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    config.runs_dir.mkdir(parents=True, exist_ok=True)
    manager = RunManager(config)

    class BoundHandler(ViewerHandler):
        pass

    BoundHandler.config = config
    BoundHandler.runs = manager
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Detroit AI Player local viewer")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()

    config = AppConfig()
    server = make_server(config, port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Detroit AI Player viewer: {url}", file=sys.stderr)
    print("Results directory:", config.results_dir, file=sys.stderr)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
