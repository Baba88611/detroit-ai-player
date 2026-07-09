from __future__ import annotations

import copy
import re
from typing import Any


def initial_state(chapter_data: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(chapter_data.get("state", {}).get("initial", {}))


def evaluate_condition(expression: str | None, state: dict[str, Any]) -> bool:
    if expression is None:
        return True

    expression = expression.strip()
    if not expression:
        return True

    tokens = _tokenize_condition(expression)
    value, pos = _parse_or(tokens, 0, state)
    if pos != len(tokens):
        raise ValueError(f"Unbalanced or malformed condition expression: {expression}")
    return value


def _tokenize_condition(expression: str) -> list[str]:
    """Split into clause / "AND" / "OR" / "(" / ")" tokens, respecting parentheses.

    Clauses keep their internal spacing (e.g. "hank_relationship < 3"); only the
    top-level boolean connectors and parentheses become structural tokens.
    """
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        clause = "".join(buffer).strip()
        if clause:
            tokens.append(clause)
        buffer.clear()

    i = 0
    n = len(expression)
    while i < n:
        char = expression[i]
        if char in "()":
            flush()
            tokens.append(char)
            i += 1
        elif expression[i : i + 4] == " OR ":
            flush()
            tokens.append("OR")
            i += 4
        elif expression[i : i + 5] == " AND ":
            flush()
            tokens.append("AND")
            i += 5
        else:
            buffer.append(char)
            i += 1
    flush()
    return tokens


def _parse_or(tokens: list[str], pos: int, state: dict[str, Any]) -> tuple[bool, int]:
    value, pos = _parse_and(tokens, pos, state)
    while pos < len(tokens) and tokens[pos] == "OR":
        right, pos = _parse_and(tokens, pos + 1, state)
        value = value or right
    return value, pos


def _parse_and(tokens: list[str], pos: int, state: dict[str, Any]) -> tuple[bool, int]:
    value, pos = _parse_atom(tokens, pos, state)
    while pos < len(tokens) and tokens[pos] == "AND":
        right, pos = _parse_atom(tokens, pos + 1, state)
        value = value and right
    return value, pos


def _parse_atom(tokens: list[str], pos: int, state: dict[str, Any]) -> tuple[bool, int]:
    if pos >= len(tokens):
        raise ValueError("Unexpected end of condition expression")

    token = tokens[pos]
    if token == "(":
        value, pos = _parse_or(tokens, pos + 1, state)
        if pos >= len(tokens) or tokens[pos] != ")":
            raise ValueError("Unbalanced parentheses in condition expression")
        return value, pos + 1
    if token in {")", "AND", "OR"}:
        raise ValueError(f"Unexpected token '{token}' in condition expression")
    return _evaluate_clause(token, state), pos + 1


def apply_effects(state: dict[str, Any], effects: dict[str, Any] | None) -> dict[str, Any]:
    if not effects:
        return state

    for key, value in effects.items():
        if key.endswith("_override"):
            state[key.removesuffix("_override")] = copy.deepcopy(value)
            continue

        current = state.get(key)
        if isinstance(current, (int, float)) and not isinstance(current, bool) and isinstance(value, (int, float)):
            state[key] = current + value
        else:
            state[key] = copy.deepcopy(value)
    return state


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(state)


def extract_cross_chapter_state(state: dict[str, Any], export_keys: list[str]) -> dict[str, Any]:
    return {key: copy.deepcopy(state[key]) for key in export_keys if key in state}


def _evaluate_clause(clause: str, state: dict[str, Any]) -> bool:
    match = re.fullmatch(r"(.+?)\s+(NOT IN|IN|==|!=|>=|<=|>|<)\s+(.+)", clause)
    if not match:
        raise ValueError(f"Unsupported condition expression: {clause}")

    left_token, operator, right_token = match.groups()
    left = _resolve_value(left_token.strip(), state)
    right = _resolve_value(right_token.strip(), state)

    if operator == "IN":
        return left in right
    if operator == "NOT IN":
        return left not in right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right

    raise ValueError(f"Unsupported operator: {operator}")


def _resolve_value(token: str, state: dict[str, Any]) -> Any:
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None

    if token in state:
        return state[token]

    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)

    return token.strip("\"'")
