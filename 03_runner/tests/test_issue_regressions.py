import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_runner" / "src"))

from resolver import resolve_post_choice_result  # noqa: E402
from runner import ScriptedAI, run_experiment  # noqa: E402


def chapter(language, number, name):
    return ROOT / "01_json" / language / f"ch{number}_{name}_{language}.json"


def node(path, node_id):
    return next(item for item in json.loads(path.read_text(encoding="utf-8"))["nodes"] if item["id"] == node_id)


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("difficulty", ["casual", "experienced", "hardcore"])
@pytest.mark.parametrize("opened_box,expected", [(True, "todd_helped"), (False, "todd_failed")])
def test_bus_terminal_check_uses_state_and_applies_effects(language, difficulty, opened_box, expected):
    terminal = node(chapter(language, "32", "battle_for_detroit"), "n013_bus_terminal")
    result = resolve_post_choice_result(
        terminal, "talk_to_todd", {"ch04_opened_box": opened_box}, difficulty
    )
    assert result == expected
    assert terminal["system"]["resolution_effects"][result]["kara_todd_persuaded"] is opened_box


class FixedRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


@pytest.mark.parametrize("language", ["zh", "en"])
def test_crane_burial_results_have_state_effects_for_each_qte_branch(language):
    crane = node(chapter(language, "11", "from_the_dead"), "n005_crane_burial")
    cases = [
        ("attempt_dodge", "casual", 0, "edge"),
        ("attempt_dodge", "experienced", 0, "edge"),
        ("attempt_dodge", "experienced", 1, "deep"),
        ("attempt_dodge", "hardcore", 0, "edge"),
        ("attempt_dodge", "hardcore", 1, "deep"),
        ("brace_impact", "casual", 0, "protected"),
        ("brace_impact", "experienced", 0, "protected"),
        ("brace_impact", "hardcore", 0, "protected"),
    ]
    for choice, difficulty, roll, depth in cases:
        result = resolve_post_choice_result(crane, choice, {}, difficulty, FixedRandom(roll))
        assert isinstance(result, str)
        assert crane["system"]["resolution_effects"][result] == {"burial_depth": depth}


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("difficulty", ["casual", "experienced", "hardcore"])
def test_ch11_run_keeps_burial_depth(language, difficulty, tmp_path):
    result = run_experiment(
        chapter(language, "11", "from_the_dead"),
        ScriptedAI({"n005_crane_burial": "attempt_dodge"}),
        difficulty=difficulty,
        output_dir=tmp_path,
        dry_run=True,
    )
    crane = next(item for item in result["decisions"] if item["node_id"] == "n005_crane_burial")
    assert crane["state_after"]["burial_depth"] in {"edge", "deep"}
    assert crane["effects_applied"]["burial_depth"] in {"edge", "deep"}


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("difficulty", ["casual", "experienced", "hardcore"])
def test_ch14_crane_jump_completes(language, difficulty, tmp_path):
    result = run_experiment(
        chapter(language, "14", "jericho"),
        ScriptedAI({"n003_bridge_crossing": "attempt_crane_jump"}),
        difficulty=difficulty,
        output_dir=tmp_path,
        dry_run=True,
    )
    assert result["ending"]["id"] == "ending_jericho"
    crossing = next(item for item in result["decisions"] if item["node_id"] == "n003_bridge_crossing")
    assert crossing["resolution_result"] == "continue"


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("difficulty", ["casual", "experienced", "hardcore"])
def test_refusing_final_demand_reaches_defined_ending(language, difficulty, tmp_path):
    result = run_experiment(
        chapter(language, "01", "the_hostage"),
        ScriptedAI({"n010_final_demand": "refuse"}),
        difficulty=difficulty,
        output_dir=tmp_path,
        dry_run=True,
    )
    assert result["ending"]["id"] == "ending_failed_to_reach"
    assert result["decisions"][-1]["node_id"] == "n010_final_demand"
    assert result["decisions"][-1]["state_after"]["success_probability"] == 0
