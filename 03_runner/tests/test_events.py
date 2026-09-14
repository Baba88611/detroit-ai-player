from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from campaign_runner import run_campaign  # noqa: E402
from events import JsonlEventWriter, read_events  # noqa: E402
from runner import ScriptedAI, run_experiment  # noqa: E402


CH01_EN = PROJECT_ROOT / "01_json" / "en" / "ch01_the_hostage_en.json"
CH01_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch01_the_hostage_zh.json"
CH03_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch03_shades_of_color_zh.json"

QTE_PATH_CHOICES = {
    "n001_fish": "leave_fish",
    "n002_investigation_strategy": "rush",
    "n004_wounded_cop": "save_cop",
    "n005_approach": "cold",
    "n006_dialogue_opening": "threaten",
    "n007_motive_response": "blaming",
    "n009_helicopter": "refuse",
    "n010_final_demand": "compromise",
    "n011_final_choice": "reassure",
    "n012_qte_leap": "leap",
}


def test_run_experiment_emits_ordered_events_with_node_shown_before_decision(tmp_path):
    events: list[dict] = []

    result = run_experiment(
        json_path=CH01_EN,
        ai_client=ScriptedAI(QTE_PATH_CHOICES),
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
        on_event=events.append,
    )

    types = [event["type"] for event in events]
    assert types[0] == "chapter_start"
    assert types[-1] == "chapter_end"
    assert "error" not in types

    # 每个 decision 前面紧挨着同一节点的 node_shown。
    for index, event in enumerate(events):
        if event["type"] == "decision":
            previous = events[index - 1]
            assert previous["type"] == "node_shown"
            assert previous["node_id"] == event["node_id"]

    decision_nodes = [event["node_id"] for event in events if event["type"] == "decision"]
    assert decision_nodes == [decision["node_id"] for decision in result["decisions"]]

    start = events[0]
    assert start["experiment_id"] == result["experiment_id"]
    assert start["chapter"]["id"] == "ch01_the_hostage"
    assert start["config"]["model"] == "scripted"

    end = events[-1]
    assert end["ending"]["id"] == result["ending"]["id"]
    assert Path(end["result_file"]).exists()


def test_node_shown_never_carries_system_layer_fields():
    events: list[dict] = []
    run_experiment(
        json_path=CH01_EN,
        ai_client=ScriptedAI(QTE_PATH_CHOICES),
        dry_run=True,
        on_event=events.append,
    )

    for event in events:
        if event["type"] != "node_shown":
            continue
        assert set(event.keys()) == {"type", "node_id", "phase", "node_type", "context", "choices"}
        for choice in event["choices"]:
            assert set(choice.keys()) == {"id", "text"}


def test_decisions_record_effects_resolution_and_latency():
    result = run_experiment(
        json_path=CH01_EN,
        ai_client=ScriptedAI(QTE_PATH_CHOICES),
        difficulty="casual",
        dry_run=True,
    )

    first = result["decisions"][0]
    assert first["node_id"] == "n001_fish"
    assert first["phase"] == "arrival"
    assert first["node_type"] == "choice"
    assert isinstance(first["latency_ms"], int)
    assert first["timestamp"]
    assert first["effects_applied"] == {}
    assert first["resolution_result"] is None

    cop = next(d for d in result["decisions"] if d["node_id"] == "n004_wounded_cop")
    assert cop["effects_applied"]["cop_saved"] is True
    assert cop["effects_applied"]["success_probability"] == -5

    qte = result["decisions"][-1]
    assert qte["node_id"] == "n012_qte_leap"
    assert qte["node_type"] == "qte_converted"
    assert qte["resolution_result"] == result["ending"]["id"]


def test_narrative_event_for_mandatory_node(tmp_path):
    chapter_path = tmp_path / "ch02_opening_en.json"
    chapter_path.write_text(
        json.dumps(
            {
                "_meta": {"language": "en-US"},
                "chapter": {"id": "ch02_opening", "title": "Opening", "chapter_number": 2, "protagonist": "Kara"},
                "system_prompt": {"content": "You are Kara."},
                "state": {"initial": {"arrived": False}},
                "nodes": [
                    {
                        "id": "n001_return_home",
                        "phase": "opening",
                        "type": "mandatory",
                        "condition": None,
                        "player_facing": {"context": "Rain slides down the window."},
                        "system": {"effects": {"arrived": True}, "result": "ending_home"},
                    }
                ],
                "endings": {
                    "ending_home": {"title": "Home", "narrative": "Home.", "survivors": ["Kara"], "deaths": []}
                },
            }
        ),
        encoding="utf-8",
    )
    events: list[dict] = []

    run_experiment(json_path=chapter_path, ai_client=ScriptedAI(), dry_run=True, on_event=events.append)

    assert [event["type"] for event in events] == ["chapter_start", "node_shown", "narrative", "chapter_end"]
    assert events[1]["choices"] == []
    assert events[2]["effects_applied"] == {"arrived": True}
    assert events[2]["resolution_result"] == "ending_home"


class ExplodingAI(ScriptedAI):
    def choose(self, node_id, context, choices, messages):
        if node_id == "n003_gun":
            raise RuntimeError("boom")
        return super().choose(node_id, context, choices, messages)


def test_error_event_is_emitted_then_reraised():
    events: list[dict] = []

    with pytest.raises(RuntimeError, match="boom"):
        run_experiment(json_path=CH01_EN, ai_client=ExplodingAI(), dry_run=True, on_event=events.append)

    assert events[-1]["type"] == "error"
    assert events[-1]["node_id"] == "n003_gun"
    assert "boom" in events[-1]["message"]


def test_campaign_events_carry_chapter_index_and_summary(tmp_path):
    events: list[dict] = []
    scripted = ScriptedAI(
        {
            "n001_fish": "save_fish",
            "n002_investigation_strategy": "thorough",
            "n003_gun": "leave_gun",
            "n004_wounded_cop": "save_cop",
            "n005_approach": "friendly",
            "n006_dialogue_opening": "use_name",
            "n007_motive_response": "possible_cause",
            "n009_helicopter": "dismiss",
            "n010_final_demand": "compromise",
            "n011_final_choice": "reassure",
            "n001_park_exploration": "direct",
            "n002_protester_encounter": "avoid",
        }
    )

    campaign = run_campaign(
        chapter_paths=[CH01_ZH, CH03_ZH],
        ai_client=scripted,
        output_dir=tmp_path,
        dry_run=True,
        on_event=events.append,
    )

    assert events[0]["type"] == "campaign_start"
    assert [chapter["id"] for chapter in events[0]["chapters"]] == ["ch01_the_hostage", "ch03_shades_of_color"]
    assert events[-1]["type"] == "campaign_end"
    assert events[-1]["status"] == "complete"
    assert [chapter["ending_id"] for chapter in events[-1]["chapters"]] == [
        chapter["ending_id"] for chapter in campaign["chapters"]
    ]

    chapter_starts = [event for event in events if event["type"] == "chapter_start"]
    assert [event["chapter_index"] for event in chapter_starts] == [1, 2]
    decisions_ch2 = [event for event in events if event["type"] == "decision" and event["chapter_index"] == 2]
    assert decisions_ch2 and all(event["node_id"].startswith("n00") for event in decisions_ch2)


def test_jsonl_writer_round_trips_with_sequential_seq(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path)
    writer({"type": "a", "value": "中文"})
    writer({"type": "b"})
    writer.close()

    events = read_events(path)
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["value"] == "中文"
    assert all("ts" in event for event in events)
    assert read_events(path, after_seq=1) == [events[1]]
    assert read_events(tmp_path / "missing.jsonl") == []


def test_runner_without_on_event_keeps_legacy_result_shape(tmp_path):
    result = run_experiment(json_path=CH01_EN, ai_client=ScriptedAI(), output_dir=tmp_path, dry_run=True)

    legacy_keys = {
        "node_id", "context_shown", "choices_shown", "ai_response_raw",
        "ai_choice_id", "ai_choice_text", "ai_reasoning", "state_after", "messages_sent",
    }
    assert legacy_keys <= set(result["decisions"][0].keys())
    assert set(result.keys()) == {"experiment_id", "timestamp", "config", "decisions", "ending", "all_endings", "token_usage"}


def test_effects_applied_matches_real_state_for_interleaved_increment_and_override():
    """增量与赋值在同一步交错时，记录重放必须等于真实状态。

    审查给出的用例：初始 0，先 +1，再「设为 4 并 +2」，真实结果是 6。
    按字面合并 effects 字典会得出 4，与实际不符。
    """
    import copy

    from state import apply_effects
    from runner import _effects_applied

    init = {"pressure_count": 0}
    groups = [{"pressure_count": 1}, {"pressure_count_override": 4, "pressure_count": 2}]

    after = copy.deepcopy(init)
    for group in groups:
        apply_effects(after, group)
    assert after["pressure_count"] == 6

    record = _effects_applied(groups, copy.deepcopy(init), after)
    replayed = apply_effects(copy.deepcopy(init), record)
    assert replayed["pressure_count"] == 6


def test_effects_applied_keeps_plain_increments_readable():
    """全程只有普通增量时仍记为增量，界面才能显示 +1 / −5。"""
    import copy

    from state import apply_effects
    from runner import _effects_applied

    init = {"success_probability": 50, "software_instability": 0}
    groups = [{"success_probability": -5, "software_instability": 1}]
    after = copy.deepcopy(init)
    for group in groups:
        apply_effects(after, group)

    record = _effects_applied(groups, copy.deepcopy(init), after)
    assert record == {"success_probability": -5, "software_instability": 1}
    assert apply_effects(copy.deepcopy(init), record) == after


def test_effects_applied_replay_equivalence_property():
    """随机化属性测试：任意效果序列，记录重放后被触及的变量都要与真实状态一致。

    合并不能只看 effects 字典——apply_effects 判断增量还是替换取决于当前状态值，
    所以记录必须从真实前后状态推导。这条测试是该保证的看门人。
    """
    import copy
    import random

    from state import apply_effects
    from runner import _effects_applied, _same_value

    random.seed(20260914)
    names = ["a", "b", "c"]
    # 取值刻意混入 0/1 与 True/False，以及含布尔的嵌套容器
    pool = [0, 1, 5, None, "x", [], True, False, 2.5, [True]]

    def random_value():
        return random.choice(
            [random.randint(-5, 5), "s1", [1], [True, 0], {"k": True}, True, False, 1.5, None, 0, 1]
        )

    for _ in range(2000):
        init = {name: random.choice(pool) for name in names}
        groups = []
        for _ in range(random.randint(1, 4)):
            group = {}
            for _ in range(random.randint(1, 3)):
                name = random.choice(names)
                key = name + "_override" if random.random() < 0.4 else name
                group[key] = random_value()
            groups.append(group)

        after = copy.deepcopy(init)
        for group in groups:
            apply_effects(after, group)

        record = _effects_applied(groups, copy.deepcopy(init), after)
        replayed = apply_effects(copy.deepcopy(init), record)
        touched = {k[: -len("_override")] if k.endswith("_override") else k for k in record}
        for name in touched:
            # 必须用区分布尔的比较：`True == 1` 会让这条断言形同虚设
            assert _same_value(replayed[name], after[name]), (init, groups, record, name)


def test_same_value_distinguishes_bool_from_number():
    """`True == 1` 在 Python 里成立，等价判断必须自己区分。"""
    from runner import _same_value

    assert not _same_value(True, 1)
    assert not _same_value(False, 0)
    assert not _same_value(1, True)
    assert _same_value(True, True)
    assert _same_value(1, 1)
    # 容器要递归，否则列表/字典里的布尔同样漏判
    assert not _same_value([True], [1])
    assert not _same_value({"k": False}, {"k": 0})
    assert _same_value([True, 2], [True, 2])
    assert _same_value({"k": [False]}, {"k": [False]})


def test_effects_applied_keeps_boolean_type_after_override():
    """布尔赋值不能被记成整数，否则后续状态更新会走上不同分支。

    初始 x=0，执行 x_override=True，真实状态是布尔 True。
    若记录成 {"x": True}，重放时 apply_effects 见当前 0 是数值、True 也算数值，
    会算成 0 + True = 1（整数）。差异还会在后续步骤放大：再执行 x:2 时，
    真实链路（当前是布尔→替换）得 2，错误链路（当前是数值→相加）得 3。
    """
    import copy

    from state import apply_effects
    from runner import _effects_applied, _same_value

    init = {"x": 0}
    groups = [{"x_override": True}]

    after = copy.deepcopy(init)
    for group in groups:
        apply_effects(after, group)
    assert after["x"] is True

    record = _effects_applied(groups, copy.deepcopy(init), after)
    replayed = apply_effects(copy.deepcopy(init), record)
    assert _same_value(replayed["x"], after["x"])
    assert replayed["x"] is True

    # 后续再走一步增量，两条链路必须仍然一致
    apply_effects(after, {"x": 2})
    apply_effects(replayed, {"x": 2})
    assert _same_value(replayed["x"], after["x"])
    assert after["x"] == 2
