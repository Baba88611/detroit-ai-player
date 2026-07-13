from __future__ import annotations

import argparse
import copy
import glob
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logger import write_campaign_result
from runner import (
    ScriptedAI,
    build_llm_client_from_model_registry,
    load_persona_prompt,
    recorded_backend_config,
    run_experiment,
)
from state import evaluate_condition, extract_cross_chapter_state


def expand_chapter_paths(raw_paths: list[str]) -> list[str]:
    """展开章节通配符（如 `../01_json/zh/ch*.json`）。

    macOS/Linux 的 shell 会替我们展开通配符，但 Windows 的 PowerShell/CMD 通常把
    `ch*.json` 原样传进来。这里由 Python 自己展开，保证三平台命令一致。展开后按
    文件名排序（`ch01`→`ch32` 恰好是章节顺序）；显式路径原样保留、保持传入顺序。
    """
    expanded: list[str] = []
    for raw_path in raw_paths:
        if glob.has_magic(raw_path):
            matches = sorted(glob.glob(raw_path))
            if not matches:
                raise ValueError(f"Pattern matched no chapter files: {raw_path}")
            expanded.extend(matches)
        else:
            expanded.append(raw_path)
    return expanded


def build_campaign_payload(
    *,
    campaign_id: str,
    ai_client: Any,
    temperature: float,
    difficulty: str,
    persona_name: str,
    dry_run: bool,
    requested_count: int,
    chapter_refs: list[dict[str, Any]],
    cross_chapter_state: dict[str, Any],
    memory_segments: list[str],
    status: str,
) -> dict[str, Any]:
    """构造 campaign 结果/检查点。同一 campaign_id 多次写入会覆盖同一文件，
    从 status=partial 逐步更新到 status=complete。"""
    completed = len(chapter_refs)
    return {
        "campaign_id": campaign_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "progress": {
            "completed": completed,
            "requested": requested_count,
            "next_chapter_index": completed + 1 if completed < requested_count else None,
        },
        "config": {
            **recorded_backend_config(ai_client, temperature),
            "difficulty": difficulty,
            "persona": persona_name,
            "dry_run": dry_run,
            "chapter_count": requested_count,
        },
        "chapters": copy.deepcopy(chapter_refs),
        "final_cross_chapter_state": copy.deepcopy(cross_chapter_state),
        "full_memory_summary": "\n\n".join(memory_segments),
    }


def build_chapter_summary(segments: list[dict[str, Any]], state: dict[str, Any]) -> str:
    parts: list[str] = []
    for segment in segments:
        if "text" in segment:
            parts.append(str(segment["text"]))
            continue

        if "condition_variable" not in segment:
            continue

        variable_name = segment["condition_variable"]
        options = segment.get("options", {})

        # Multi-protagonist finales collect one ending per track. Narrate every
        # collected ending (Connor / Markus / Kara), not just the primary one.
        if variable_name == "_ending_id" and isinstance(state.get("_ending_ids"), list):
            for ending_id in state["_ending_ids"]:
                text = options.get(str(ending_id))
                if text:
                    parts.append(str(text))
            continue

        variable_value = str(state.get(variable_name, ""))
        text = options.get(variable_value)
        if text:
            parts.append(str(text))

    return "".join(parts)


def apply_derived_exports(
    state: dict[str, Any],
    derived_exports: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    ending = result.get("ending", {})
    survivors = ending.get("survivors", [])
    deaths = ending.get("deaths", [])

    for rule in derived_exports:
        target = rule.get("target")
        if not target:
            continue

        if "source" in rule:
            source = rule["source"]
            if "derive_rule" in rule:
                state[target] = evaluate_condition(rule["derive_rule"], state)
                continue
            if source in state:
                state[target] = copy.deepcopy(state[source])
            continue

        if "from_ending_survivors" in rule:
            name = str(rule["from_ending_survivors"])
            survived = _contains_name(survivors, name)
            died = _contains_name(deaths, name)
            state[target] = survived or (bool(rule.get("default_if_not_dead")) and not died)
            continue

        if "from_ending_deaths" in rule:
            name = str(rule["from_ending_deaths"])
            value = _contains_name(deaths, name)
            state[target] = not value if rule.get("invert") else value


def run_campaign(
    chapter_paths: list[str | Path],
    ai_client: Any,
    difficulty: str = "casual",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    temperature: float = 0.7,
    persona_name: str = "default",
    persona_text: str | None = None,
) -> dict[str, Any]:
    campaign_id = str(uuid.uuid4())
    cross_chapter_state: dict[str, Any] = {}
    memory_segments: list[str] = []
    chapter_refs: list[dict[str, Any]] = []

    for chapter_index, chapter_path in enumerate(chapter_paths, start=1):
        chapter_data = json.loads(Path(chapter_path).read_text(encoding="utf-8"))
        memory_summary = _build_memory_summary(chapter_data, memory_segments)

        result = run_experiment(
            json_path=chapter_path,
            ai_client=ai_client,
            difficulty=difficulty,
            output_dir=output_dir,
            dry_run=dry_run,
            temperature=temperature,
            persona_name=persona_name,
            persona_text=persona_text,
            cross_chapter_state=cross_chapter_state if cross_chapter_state else None,
            memory_summary=memory_summary,
        )

        final_state = copy.deepcopy(result["decisions"][-1]["state_after"])
        _add_campaign_derived_state(final_state, chapter_data, result)

        campaign_config = chapter_data.get("campaign", {})
        apply_derived_exports(final_state, campaign_config.get("derived_exports", []), result)
        new_exports = extract_cross_chapter_state(
            final_state,
            campaign_config.get("cross_chapter_exports", []),
        )
        cross_chapter_state.update(new_exports)

        summary = build_chapter_summary(campaign_config.get("summary_segments", []), final_state)
        if summary:
            memory_segments.append(summary)

        chapter_refs.append(
            {
                "chapter_index": chapter_index,
                "chapter": result["config"]["chapter"],
                "experiment_id": result["experiment_id"],
                "ending_id": result["ending"]["id"],
                "token_usage": result.get("token_usage", {}),
            }
        )

        # 每完成一章就覆盖写入同一个 campaign 检查点（status=partial）。长任务
        # 若在后续章节中断，用户仍能拿到一个说明整体进度和跨章状态的 campaign 文件。
        if output_dir:
            checkpoint = build_campaign_payload(
                campaign_id=campaign_id,
                ai_client=ai_client,
                temperature=temperature,
                difficulty=difficulty,
                persona_name=persona_name,
                dry_run=dry_run,
                requested_count=len(chapter_paths),
                chapter_refs=chapter_refs,
                cross_chapter_state=cross_chapter_state,
                memory_segments=memory_segments,
                status="partial",
            )
            write_campaign_result(checkpoint, output_dir)

    campaign_result = build_campaign_payload(
        campaign_id=campaign_id,
        ai_client=ai_client,
        temperature=temperature,
        difficulty=difficulty,
        persona_name=persona_name,
        dry_run=dry_run,
        requested_count=len(chapter_paths),
        chapter_refs=chapter_refs,
        cross_chapter_state=cross_chapter_state,
        memory_segments=memory_segments,
        status="complete",
    )

    # 全部完成后再写一次同一文件，把 status 从 partial 更新为 complete。
    if output_dir:
        write_campaign_result(campaign_result, output_dir)

    return campaign_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a multi-chapter Detroit campaign experiment.")
    parser.add_argument("--chapters", nargs="+", required=True, help="Chapter JSON paths in campaign order")
    parser.add_argument("--model", help="Model id from ../02_setting/models.json")
    parser.add_argument("--difficulty", default="casual", choices=["casual", "experienced", "hardcore"])
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--persona", default="default", help="Persona prompt name from ../02_setting/personas/")
    parser.add_argument("--output", default="../04_execution/results/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    personas_dir = Path(__file__).resolve().parents[2] / "02_setting" / "personas"
    persona_text = load_persona_prompt(args.persona, personas_dir)

    if args.dry_run:
        ai_client = ScriptedAI()
    else:
        from dotenv import load_dotenv

        if not args.model:
            raise SystemExit("--model is required for real API runs")

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        registry_path = Path(__file__).resolve().parents[2] / "02_setting" / "models.json"
        ai_client = build_llm_client_from_model_registry(
            model_id=args.model,
            registry_path=registry_path,
            temperature=args.temperature,
        )

    chapter_paths = expand_chapter_paths(args.chapters)
    result = run_campaign(
        chapter_paths=chapter_paths,
        ai_client=ai_client,
        difficulty=args.difficulty,
        output_dir=args.output,
        dry_run=args.dry_run,
        temperature=args.temperature,
        persona_name=args.persona,
        persona_text=persona_text,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _build_memory_summary(chapter_data: dict[str, Any], memory_segments: list[str]) -> str | None:
    if not memory_segments:
        return None

    language = chapter_data.get("_meta", {}).get("language", "en")
    header = "以下是此前在这个游戏中发生的事：" if "zh" in language else "Here is what happened previously in this game:"
    return f"{header}\n\n" + "\n\n".join(memory_segments)


def _add_campaign_derived_state(
    final_state: dict[str, Any],
    chapter_data: dict[str, Any],
    result: dict[str, Any],
) -> None:
    ending = result["ending"]
    ending_id = ending["id"]
    chapter_id = chapter_data["chapter"]["id"]
    chapter_prefix = chapter_id.split("_", 1)[0]

    final_state["_ending_id"] = ending_id
    final_state["_ending_ids"] = [item["id"] for item in result.get("all_endings", [ending])]
    final_state[f"{chapter_prefix}_ending"] = ending_id
    final_state["connor_death_count"] = int(final_state.get("connor_death_count", 0))

    deaths = ending.get("deaths", [])
    if any(str(death).startswith("Connor") for death in deaths):
        final_state["connor_death_count"] = int(final_state.get("connor_death_count", 0)) + 1


def _contains_name(values: list[Any], name: str) -> bool:
    aliases = _name_aliases(name)
    return any(any(alias in str(value) for alias in aliases) for value in values)


def _name_aliases(name: str) -> list[str]:
    aliases = {
        "Connor": ["Connor", "康纳"],
        "Emma": ["Emma", "艾玛"],
        "Daniel": ["Daniel", "丹尼尔"],
        "Markus": ["Markus", "马库斯"],
    }
    return aliases.get(name, [name])


if __name__ == "__main__":
    main()
