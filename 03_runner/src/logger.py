from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def write_result(result: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = _build_filename(result)
    file_path = output_path / filename
    file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # 把绝对路径打到 stderr，用户/agent 跑完能立刻定位结果文件（stdout 留给结果 JSON）。
    print(f"Saved chapter result: {file_path.resolve()}", file=sys.stderr)
    return file_path


def write_campaign_result(result: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = _build_campaign_filename(result)
    file_path = output_path / filename
    file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    status = result.get("status", "unknown")
    print(f"Saved campaign result [{status}]: {file_path.resolve()}", file=sys.stderr)
    return file_path


def _build_filename(result: dict[str, Any]) -> str:
    config = result.get("config", {})
    chapter = config.get("chapter", "unknown")
    model = config.get("model", "unknown")
    persona = config.get("persona", "default")
    difficulty = config.get("difficulty", "casual")
    experiment_id = result.get("experiment_id", "unknown")[:8]
    return f"{chapter}_{model}_{persona}_{difficulty}_{experiment_id}.json"


def _build_campaign_filename(result: dict[str, Any]) -> str:
    config = result.get("config", {})
    model = config.get("model", "unknown")
    persona = config.get("persona", "default")
    difficulty = config.get("difficulty", "casual")
    campaign_id = result.get("campaign_id", "unknown")[:8]
    return f"campaign_{model}_{persona}_{difficulty}_{campaign_id}.json"
