from __future__ import annotations

import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
SERVE_PATH = PROJECT_ROOT / "05_viewer" / "serve.py"


def _load_serve_module():
    spec = importlib.util.spec_from_file_location("detroit_viewer_serve", SERVE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def serve():
    return _load_serve_module()


@pytest.fixture
def server(serve, tmp_path):
    config = serve.AppConfig(
        project_root=PROJECT_ROOT,
        results_dir=tmp_path / "results",
        runs_dir=tmp_path / "runs",
    )
    httpd = serve.make_server(config, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, config
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict, content_type: str = "application/json"):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _status(base: str, path: str) -> int:
    try:
        with urllib.request.urlopen(base + path, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_meta_lists_models_personas_chapters_without_secret_values(server, monkeypatch):
    base, _ = server
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "example-chat")

    status, meta = _get(base, "/api/meta")

    assert status == 200
    assert meta["mode"] == "local"
    models = {item["id"]: item for item in meta["models"]}
    assert models["default"]["configured"] is True
    assert models["default"]["missing"] == []
    assert models["codex-cli"]["experimental_backend"] is True
    assert models["codex-cli"]["provider"] == "cli"
    assert [item["id"] for item in meta["personas"]] == ["default", "machine"]
    assert len(meta["chapters"]["zh"]) == 32
    assert len(meta["chapters"]["en"]) == 32
    assert meta["chapters"]["en"][0]["id"] == "ch01_the_hostage"
    assert "sk-super-secret-value" not in json.dumps(meta)
    assert "example-chat" not in json.dumps(meta)


def test_dry_run_chapter_streams_events_and_writes_result(server):
    base, config = server

    status, run = _post(
        base,
        "/api/runs",
        {"mode": "chapter", "dry_run": True, "language": "en", "chapter_ids": ["ch01_the_hostage"]},
    )
    assert status == 201, run
    run_id = run["run_id"]
    assert run["status"] == "running"

    deadline = time.time() + 30
    events: list[dict] = []
    final_status = None
    while time.time() < deadline:
        _, payload = _get(base, f"/api/runs/{run_id}/events?after={events[-1]['seq'] if events else 0}")
        events.extend(payload["events"])
        final_status = payload["status"]
        if final_status in ("finished", "failed"):
            break
        time.sleep(0.2)

    assert final_status == "finished", payload
    types = [event["type"] for event in events]
    assert types[0] == "chapter_start"
    assert "decision" in types
    assert types[-1] == "chapter_end"
    assert Path(events[-1]["result_file"]).parent == config.results_dir
    assert list(config.results_dir.glob("ch01_the_hostage_scripted_*.json"))

    _, listing = _get(base, "/api/results")
    assert listing["results"][0]["kind"] == "chapter"
    assert listing["results"][0]["chapter"] == "ch01_the_hostage"
    name = listing["results"][0]["name"]
    status, result = _get(base, f"/api/results/{name}")
    assert status == 200
    assert result["ending"]["id"]

    _, runs = _get(base, "/api/runs")
    assert runs["runs"][0]["run_id"] == run_id
    assert runs["runs"][0]["status"] == "finished"


def test_dry_run_campaign_defaults_to_all_chapters_and_reports_index(server):
    base, _ = server

    status, run = _post(base, "/api/runs", {"mode": "campaign", "dry_run": True, "language": "zh", "chapter_ids": ["ch01_the_hostage", "ch02_opening"]})
    assert status == 201, run
    run_id = run["run_id"]
    assert run["chapter_ids"] == ["ch01_the_hostage", "ch02_opening"]

    deadline = time.time() + 30
    while time.time() < deadline:
        _, payload = _get(base, f"/api/runs/{run_id}/events?after=0")
        if payload["status"] in ("finished", "failed"):
            break
        time.sleep(0.2)
    assert payload["status"] == "finished", payload
    types = [event["type"] for event in payload["events"]]
    assert types[0] == "campaign_start"
    assert types[-1] == "campaign_end"
    assert {event.get("chapter_index") for event in payload["events"] if event["type"] == "chapter_start"} == {1, 2}


def test_run_request_validation(server):
    base, _ = server

    assert _post(base, "/api/runs", {"mode": "chapter", "dry_run": True, "chapter_ids": []})[0] == 400
    assert _post(base, "/api/runs", {"mode": "chapter", "dry_run": True, "chapter_ids": ["../../etc/passwd"]})[0] == 400
    assert _post(base, "/api/runs", {"mode": "chapter", "model": "not-registered", "chapter_ids": ["ch01_the_hostage"]})[0] == 400
    assert _post(base, "/api/runs", {"mode": "chapter", "dry_run": True, "persona": "../evil", "chapter_ids": ["ch01_the_hostage"]})[0] == 400
    assert _post(base, "/api/runs", {"mode": "chapter", "dry_run": True, "difficulty": "impossible", "chapter_ids": ["ch01_the_hostage"]})[0] == 400
    # 非 JSON Content-Type 直接拒绝（顺带挡住跨站表单提交）。
    assert _post(base, "/api/runs", {"mode": "chapter", "dry_run": True, "chapter_ids": ["ch01_the_hostage"]}, content_type="text/plain")[0] == 400


def test_result_and_sample_paths_reject_traversal(server):
    base, _ = server

    assert _status(base, "/api/results/../../03_runner/.env") in (400, 404)
    assert _status(base, "/api/results/..%2F..%2F03_runner%2F.env") in (400, 404)
    assert _status(base, "/api/results/nope.json") == 404
    assert _status(base, "/samples/../serve.py") in (400, 404)
    assert _status(base, "/03_runner/.env") == 404
    assert _status(base, "/api/runs/zzzzzzzz") == 404
