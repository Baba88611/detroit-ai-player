#!/usr/bin/env python3
"""重建 samples/index.json：静态回放模式（如 GitHub Pages）没有 /api/results，
页面改读这个清单。把结果 JSON 放进本目录后运行：python 05_viewer/samples/build_index.py
只收录用当前 01_json 生成的结果（见 05_viewer/CLAUDE.md）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SAMPLES_DIR.parent))
from serve import AppConfig, list_results  # noqa: E402


def main() -> None:
    config = AppConfig(project_root=SAMPLES_DIR.parents[1], results_dir=SAMPLES_DIR)
    samples = list_results(config)
    (SAMPLES_DIR / "index.json").write_text(
        json.dumps({"samples": samples}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"indexed {len(samples)} sample(s) -> {SAMPLES_DIR / 'index.json'}")


if __name__ == "__main__":
    main()
