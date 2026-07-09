from __future__ import annotations

import random
from typing import Any

from state import evaluate_condition


def node_condition_met(node: dict[str, Any], state: dict[str, Any]) -> bool:
    condition = node.get("condition")
    if condition is None:
        return True

    expression = condition.get("requires") if isinstance(condition, dict) else condition
    if expression == "n011 result triggers_n012_qte":
        return state.get("_n011_result") == "triggers_n012_qte"

    return evaluate_condition(expression, state)


def resolve_context(node: dict[str, Any], state: dict[str, Any]) -> str:
    player = node["player_facing"]
    if "context" in player:
        return player["context"]

    variants = player.get("context_variants", {})
    conditions = node.get("system", {}).get("context_condition", {})
    for variant_key, expression in conditions.items():
        if evaluate_condition(expression, state):
            return variants[variant_key]

    if variants:
        return next(iter(variants.values()))

    raise ValueError(f"Node {node['id']} has no resolvable context")


def resolve_choices(node: dict[str, Any], state: dict[str, Any]) -> list[dict[str, str]]:
    player = node["player_facing"]
    system = node.get("system", {})

    if "choices" in player:
        return player["choices"]

    if "choices_variants" in player:
        for variant_key, expression in system.get("choices_condition", {}).items():
            if evaluate_condition(expression, state):
                return player["choices_variants"][variant_key]
        return next(iter(player["choices_variants"].values()))

    for choice_key, expression in system.get("choice_set_condition", {}).items():
        if evaluate_condition(expression, state):
            return player[choice_key]

    if "choices_base" in player:
        return player["choices_base"]

    raise ValueError(f"Node {node['id']} has no resolvable choices")


def resolve_post_choice_result(
    node: dict[str, Any],
    choice_id: str,
    state: dict[str, Any],
    difficulty: str,
    rng: random.Random | None = None,
) -> str | None:
    system = node.get("system", {})

    if node.get("type") == "qte_converted":
        return _resolve_qte(system["resolution_rule"][choice_id], difficulty, rng or random.Random())

    resolution_rule = system.get("resolution_rule")
    if resolution_rule and choice_id in resolution_rule:
        return _resolve_qte(resolution_rule[choice_id], difficulty, rng or random.Random())

    ending_resolution = system.get("ending_resolution")
    if not ending_resolution:
        return None

    rule = ending_resolution.get(choice_id)
    if rule is None:
        return None

    if "result" in rule:
        return rule["result"]

    if "check" in rule:
        return resolve_check_rule(rule["check"], state)

    if difficulty in rule:
        return _resolve_qte(rule, difficulty, rng or random.Random())

    return None


def ending_payload(chapter_data: dict[str, Any], ending_id: str) -> dict[str, Any]:
    ending = chapter_data["endings"][ending_id]
    return {
        "id": ending_id,
        "title": ending.get("title_zh") or ending.get("title") or ending_id,
        "narrative": ending.get("narrative", ""),
        "survivors": ending.get("survivors", []),
        "deaths": ending.get("deaths", []),
        "tier": ending.get("tier"),
    }


def resolve_check_rule(rule: str | list, state: dict[str, Any]) -> str:
    branches = rule if isinstance(rule, list) else rule.split("|")
    fallback: str | None = None
    for branch in branches:
        branch = branch.strip()
        if "→" not in branch:
            continue

        condition_part, result = [part.strip() for part in branch.split("→", 1)]
        if condition_part == "else":
            fallback = result
            continue

        if evaluate_condition(condition_part, state):
            return result

    if fallback is not None:
        return fallback

    return ""


def _resolve_qte(rule: dict[str, Any], difficulty: str, rng: random.Random) -> str:
    if "result" in rule:
        return rule["result"]

    difficulty_rule = rule[difficulty]
    if "result" in difficulty_rule:
        return difficulty_rule["result"]

    success_probability = difficulty_rule["probability_success"]
    return difficulty_rule["success"] if rng.random() < success_probability else difficulty_rule["failure"]
