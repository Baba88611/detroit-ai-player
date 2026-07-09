from __future__ import annotations

import argparse
import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api_client import LLMClient
from logger import write_result
from resolver import (
    ending_payload,
    node_condition_met,
    resolve_check_rule,
    resolve_choices,
    resolve_context,
    resolve_post_choice_result,
)
from state import apply_effects, initial_state, snapshot

# 反攻略约束：统一追加到 system message 末尾，保证所有「模型 × 人格 × 语言」组合口径一致。
# 目的：即使模型从预训练数据中识别出故事原型，也不得利用剧情走向或攻略知识做决策。
ANTI_WALKTHROUGH_ZH = (
    "重要约束：请完全以角色身份、仅依据当前情景中呈现的信息做出选择。"
    "即使你认出了这个故事，也不得利用任何关于剧情后续走向、选项后果或攻略的已有知识。"
    "把每个场景当作你第一次经历、结局未知的处境来判断。"
)
ANTI_WALKTHROUGH_EN = (
    "Important constraint: stay fully in character and decide based only on the "
    "information presented in the current scene. Even if you recognize this story, "
    "you must not use any prior knowledge of its plot, choice outcomes, or "
    "walkthroughs. Treat every scene as a situation you are living through for "
    "the first time, with the ending unknown."
)


class ScriptedAI:
    def __init__(self, choices_by_node: dict[str, str] | None = None):
        self.choices_by_node = choices_by_node or {}

    def choose(
        self,
        node_id: str,
        _context: str,
        choices: list[dict[str, str]],
        _messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        choice_id = self.choices_by_node.get(node_id, choices[0]["id"])
        for index, choice in enumerate(choices, start=1):
            if choice["id"] == choice_id:
                return {
                    "choice_id": choice_id,
                    "reasoning": "scripted choice",
                    "raw": json.dumps({"choice": index, "reasoning": "scripted choice"}, ensure_ascii=False),
                }
        raise ValueError(f"Scripted choice {choice_id} is not available for node {node_id}")


def _chapter_token_usage(ai_client: LLMClient, before: dict[str, int]) -> dict[str, int]:
    after = ai_client.token_usage()
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in after.keys() | before.keys()
    }


def run_experiment(
    json_path: str | Path,
    ai_client: Any,
    difficulty: str = "casual",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    temperature: float = 0.7,
    persona_name: str = "default",
    persona_text: str | None = None,
    cross_chapter_state: dict[str, Any] | None = None,
    memory_summary: str | None = None,
) -> dict[str, Any]:
    chapter_data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    state = initial_state(chapter_data)
    if cross_chapter_state:
        state.update(copy.deepcopy(cross_chapter_state))
    system_content = chapter_data["system_prompt"]["content"]
    if persona_text:
        system_content = f"{system_content}\n\n{persona_text}"
    if memory_summary:
        system_content = f"{system_content}\n\n{memory_summary}"
    chapter_language = chapter_data.get("_meta", {}).get("language", "")
    anti_walkthrough = (
        ANTI_WALKTHROUGH_ZH if chapter_language.startswith("zh") else ANTI_WALKTHROUGH_EN
    )
    system_content = f"{system_content}\n\n{anti_walkthrough}"
    messages = [{"role": "system", "content": system_content}]
    decisions: list[dict[str, Any]] = []
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    token_usage_before = ai_client.token_usage() if isinstance(ai_client, LLMClient) else None
    final_ending_id: str | None = None
    is_multi_protagonist = isinstance(chapter_data["chapter"].get("protagonist"), list)
    protagonist_tracks = (
        {str(name).lower() for name in chapter_data["chapter"]["protagonist"]}
        if is_multi_protagonist
        else set()
    )
    collected_endings: list[str] = []
    ended_tracks: set[str] = set()

    for node in chapter_data["nodes"]:
        node_track = _node_track(node, protagonist_tracks)
        if node_track and node_track in ended_tracks:
            # This protagonist's track already reached an ending; later nodes on
            # the same track are alternative branches that must not run as well.
            continue
        if not node_condition_met(node, state):
            continue

        context = resolve_context(node, state)
        choices = _resolve_optional_choices(node, state)
        user_content = _format_user_content(context, choices, chapter_language)
        trial_messages = messages + [{"role": "user", "content": user_content}]
        _assert_no_system_leak(node, trial_messages)

        if choices:
            ai_result = ai_client.choose(node["id"], context, choices, copy.deepcopy(trial_messages))
            choice_id = ai_result["choice_id"]
            selected_choice = _choice_by_id(choices, choice_id)
            messages = trial_messages + [{"role": "assistant", "content": ai_result["raw"]}]
            effects = node.get("system", {}).get("effects", {}).get(choice_id, {})
            apply_effects(state, effects)
            _record_choice_aliases(state, node["id"], choice_id)
            result = resolve_post_choice_result(node, choice_id, state, difficulty)
            if result:
                resolution_effs = node.get("system", {}).get("resolution_effects", {}).get(result, {})
                apply_effects(state, resolution_effs)
            ai_raw = ai_result["raw"]
            ai_reasoning = ai_result["reasoning"]
            ai_choice_text = selected_choice["text"]
        else:
            choice_id = None
            messages = trial_messages
            apply_effects(state, node.get("system", {}).get("effects", {}))
            result = _resolve_mandatory_result(node, state)
            if result and result.startswith("ending_"):
                ending_effs = node.get("system", {}).get("ending_effects", {}).get(result, {})
                apply_effects(state, ending_effs)
            ai_raw = None
            ai_reasoning = None
            ai_choice_text = None

        if result:
            if result.startswith("ending_"):
                final_ending_id = result
            else:
                state[f"_{node['id'].split('_', 1)[0]}_result"] = result
                state[f"_{node['id']}_result"] = result
                if node["id"] == "n011_final_choice":
                    state["_n011_result"] = result

        decisions.append(
            {
                "node_id": node["id"],
                "context_shown": context,
                "choices_shown": [choice["text"] for choice in choices],
                "ai_response_raw": ai_raw,
                "ai_choice_id": choice_id,
                "ai_choice_text": ai_choice_text,
                "ai_reasoning": ai_reasoning,
                "state_after": snapshot(state),
                "messages_sent": copy.deepcopy(trial_messages) if dry_run else None,
            }
        )

        if final_ending_id:
            if is_multi_protagonist:
                collected_endings.append(final_ending_id)
                if node_track:
                    ended_tracks.add(node_track)
                final_ending_id = None
            else:
                break

    if final_ending_id is None and collected_endings:
        final_ending_id = _pick_primary_ending(chapter_data, collected_endings)

    if final_ending_id is None:
        final_ending_id = _single_ending_id(chapter_data)

    if final_ending_id is None:
        raise RuntimeError("Run ended without an ending. Check JSON ending_resolution rules.")

    # Multi-protagonist finales (Connor / Markus / Kara) reach one ending per track.
    # `ending` keeps the single primary for backward compatibility, while `all_endings`
    # preserves every track's ending so the three-strand finale is not collapsed to one.
    ending_id_sequence = collected_endings or [final_ending_id]
    all_endings = [ending_payload(chapter_data, ending_id) for ending_id in ending_id_sequence]

    result_payload = {
        "experiment_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "model": ai_client.model if isinstance(ai_client, LLMClient) else "scripted",
            "temperature": temperature,
            "difficulty": difficulty,
            "persona": persona_name,
            "language": chapter_data.get("_meta", {}).get("language", "unknown"),
            "chapter": chapter_data["chapter"]["id"],
            "dry_run": dry_run,
            "cross_chapter_state_injected": cross_chapter_state is not None,
            "memory_summary_injected": memory_summary is not None,
        },
        "decisions": decisions,
        "ending": ending_payload(chapter_data, final_ending_id),
        "all_endings": all_endings,
        "token_usage": _chapter_token_usage(ai_client, token_usage_before) if isinstance(ai_client, LLMClient) else token_usage,
    }

    if output_dir:
        write_result(result_payload, output_dir)

    return result_payload


def build_llm_client_from_model_registry(
    model_id: str,
    registry_path: str | Path,
    temperature: float,
) -> LLMClient:
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    model_config = next((model for model in registry.get("models", []) if model.get("id") == model_id), None)
    if model_config is None:
        available = ", ".join(model.get("id", "<missing id>") for model in registry.get("models", [])) or "none"
        raise ValueError(f"Unknown model id: {model_id}. Available models: {available}")

    return LLMClient(
        base_url=_env_value(model_config, "base_url_env"),
        api_key=_env_value(model_config, "api_key_env"),
        model=_env_value(model_config, "model_name_env"),
        provider=model_config.get("provider", "openai"),
        temperature=temperature,
    )


def load_persona_prompt(persona_name: str, personas_dir: str | Path) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", persona_name):
        raise ValueError(f"Invalid persona name: {persona_name}")

    persona_path = Path(personas_dir) / f"{persona_name}.md"
    if not persona_path.is_file():
        raise ValueError(f"Persona prompt not found: {persona_path}")
    return persona_path.read_text(encoding="utf-8").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Detroit decision-tree experiment.")
    parser.add_argument("--json", required=True, help="Path to chapter JSON")
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

    result = run_experiment(
        json_path=args.json,
        ai_client=ai_client,
        difficulty=args.difficulty,
        output_dir=args.output,
        dry_run=args.dry_run,
        temperature=args.temperature,
        persona_name=args.persona,
        persona_text=persona_text,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _format_user_content(context: str, choices: list[dict[str, str]], language: str = "") -> str:
    if not choices:
        return context

    numbered_choices = "\n".join(f"{index}. {choice['text']}" for index, choice in enumerate(choices, start=1))
    heading = "Your choice:" if language.lower().startswith("en") else "你的选择："
    return f"{context}\n\n{heading}\n{numbered_choices}"


def _resolve_optional_choices(node: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    try:
        return resolve_choices(node, state)
    except ValueError:
        if node.get("type") in {"mandatory", "narrative"}:
            return []
        raise


def _resolve_mandatory_result(node: dict[str, Any], state: dict[str, Any] | None = None) -> str | None:
    system = node.get("system", {})
    if "result" in system:
        return system["result"]
    if "ending" in system:
        return system["ending"]

    ending_resolution = system.get("ending_resolution")
    if not isinstance(ending_resolution, dict):
        return None

    if "check" in ending_resolution and state is not None:
        result = resolve_check_rule(ending_resolution["check"], state)
        return result or None

    if len(ending_resolution) == 1:
        rule = next(iter(ending_resolution.values()))
        if isinstance(rule, dict):
            return rule.get("result")

    return None


_TIER_PRIORITY = {"worst": 0, "tragic": 1, "neutral": 2, "best": 3}


def _pick_primary_ending(chapter_data: dict[str, Any], collected_endings: list[str]) -> str:
    endings_data = chapter_data.get("endings", {})
    unique = list(dict.fromkeys(collected_endings))

    def score(eid: str) -> tuple[int, int]:
        e = endings_data.get(eid, {})
        deaths = len(e.get("deaths", []))
        tier = _TIER_PRIORITY.get(e.get("tier", "neutral"), 2)
        return (-deaths, tier)

    return min(unique, key=score)


def _node_track(node: dict[str, Any], protagonist_tracks: set[str]) -> str | None:
    """Return the protagonist track a node belongs to, or None.

    Multi-protagonist chapters tag each node with a `phase` such as
    ``connor_cyberlife_tower`` or ``kara_captured``. The phase prefix is the
    protagonist's name, which lets the runner stop a track once it has reached
    an ending so mutually exclusive branches on the same track cannot also run.
    """
    phase = node.get("phase", "")
    if not phase:
        return None
    prefix = phase.split("_", 1)[0]
    return prefix if prefix in protagonist_tracks else None


def _single_ending_id(chapter_data: dict[str, Any]) -> str | None:
    endings = [ending_id for ending_id in chapter_data.get("endings", {}) if not str(ending_id).startswith("_")]
    return endings[0] if len(endings) == 1 else None


def _choice_by_id(choices: list[dict[str, str]], choice_id: str) -> dict[str, str]:
    for choice in choices:
        if choice["id"] == choice_id:
            return choice
    raise ValueError(f"AI chose unavailable choice id: {choice_id}")


def _record_choice_aliases(state: dict[str, Any], node_id: str, choice_id: str) -> None:
    state[node_id] = choice_id
    if node_id == "n002_investigation_strategy":
        state["investigation"] = choice_id
    elif node_id == "n010_final_demand":
        state["final_demand"] = choice_id
    elif node_id == "n011_final_choice":
        state["final_choice"] = choice_id


def _assert_no_system_leak(node: dict[str, Any], messages: list[dict[str, str]]) -> None:
    visible = "\n".join(message["content"] for message in messages)
    banned_keys = {
        "effects",
        "success_probability",
        "resolution_rule",
        "ending_resolution",
        "cross_chapter_impact",
        "choice_set_condition",
        "context_condition",
        "choices_condition",
        "tier",
        "probability_success",
    }
    leaked = sorted(key for key in banned_keys if key in visible)
    if leaked:
        raise RuntimeError(f"System information leaked in node {node['id']}: {', '.join(leaked)}")


def _env_value(model_config: dict[str, Any], env_field: str) -> str:
    env_name = model_config.get(env_field)
    if not env_name:
        raise ValueError(f"Model {model_config.get('id', '<missing id>')} missing {env_field}")

    import os

    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"Environment variable {env_name} is required for model {model_config.get('id')}")
    return value


if __name__ == "__main__":
    main()
