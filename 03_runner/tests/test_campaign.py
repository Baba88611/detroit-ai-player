from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from campaign_runner import (  # noqa: E402
    apply_derived_exports,
    build_chapter_summary,
    expand_chapter_paths,
    run_campaign,
)
from api_client import LLMClient  # noqa: E402
from runner import ScriptedAI, run_experiment  # noqa: E402
from resolver import ending_payload, resolve_post_choice_result  # noqa: E402
from state import extract_cross_chapter_state  # noqa: E402


CH01_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch01_the_hostage_zh.json"
CH03_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch03_shades_of_color_zh.json"


class CountingLLMClient(LLMClient):
    def __init__(self, choices_by_node: dict[str, str] | None = None):
        self.model = "counting-llm"
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.choices_by_node = choices_by_node or {}

    def choose(self, node_id, _context, choices, _messages):
        self.total_prompt_tokens += 100
        self.total_completion_tokens += 10
        choice_id = self.choices_by_node.get(node_id, choices[0]["id"])
        for index, choice in enumerate(choices, start=1):
            if choice["id"] == choice_id:
                return {
                    "choice_id": choice_id,
                    "reasoning": "counted choice",
                    "raw": json.dumps({"choice": index, "reasoning": "counted choice"}, ensure_ascii=False),
                }
        raise ValueError(f"Counting choice {choice_id} is not available for node {node_id}")


def write_mandatory_ch02(tmp_path: Path) -> Path:
    chapter_path = tmp_path / "ch02_opening_zh.json"
    chapter_path.write_text(
        json.dumps(
            {
                "_meta": {"language": "zh-CN"},
                "chapter": {
                    "id": "ch02_opening",
                    "title": "Opening",
                    "title_zh": "开场",
                    "chapter_number": 2,
                    "protagonist": "Kara",
                },
                "system_prompt": {
                    "content": "你是卡拉（Kara）。托德刚把你从商店取回家。"
                },
                "state": {"initial": {"kara_arrived_home": False}},
                "nodes": [
                    {
                        "id": "n001_return_home",
                        "phase": "opening",
                        "type": "mandatory",
                        "condition": None,
                        "player_facing": {
                            "context": "雨水滑过车窗。你坐在副驾驶座上，托德沉默地开车，把你带回那栋昏暗的房子。此刻没有需要你决定的事。"
                        },
                        "system": {
                            "effects": {"kara_arrived_home": True},
                            "result": "ending_kara_arrived_home",
                        },
                    }
                ],
                "endings": {
                    "_note": "Pure narrative chapter.",
                    "ending_kara_arrived_home": {
                        "title_zh": "卡拉回到托德家",
                        "narrative": "托德把卡拉带回家。屋子里安静、凌乱，爱丽丝在楼上等待。",
                        "survivors": ["Kara", "Alice", "Todd"],
                        "deaths": [],
                    },
                },
                "campaign": {
                    "summary_segments": [
                        {"text": "卡拉被托德从商店取回，回到了那栋昏暗的家。"}
                    ],
                    "cross_chapter_exports": ["kara_arrived_home"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return chapter_path


def write_fatal_survivor_chapter(tmp_path: Path) -> Path:
    chapter_path = tmp_path / "ch99_fatal_survivor_en.json"
    chapter_path.write_text(
        json.dumps(
            {
                "_meta": {"language": "en-US"},
                "chapter": {
                    "id": "ch99_fatal_survivor",
                    "title": "Fatal Survivor",
                    "chapter_number": 99,
                    "protagonist": "Kara",
                },
                "system_prompt": {"content": "You are Kara."},
                "state": {"initial": {}},
                "nodes": [
                    {
                        "id": "n001_crash",
                        "phase": "ending",
                        "type": "mandatory",
                        "condition": None,
                        "player_facing": {"context": "The road disappears under headlights."},
                        "system": {"effects": {}, "result": "ending_kara_died"},
                    }
                ],
                "endings": {
                    "ending_kara_died": {
                        "tier": "fatal",
                        "title": "Kara Died",
                        "narrative": "Kara died on the road.",
                        "survivors": ["Alice"],
                        "deaths": ["Kara"],
                    }
                },
                "campaign": {
                    "summary_segments": [
                        {
                            "condition_variable": "_ending_id",
                            "options": {"ending_kara_died": "Kara died while Alice survived."},
                        }
                    ],
                    "derived_exports": [
                        {
                            "target": "ch99_kara_alive",
                            "from_ending_survivors": "Kara",
                            "default_if_not_dead": True,
                        },
                        {
                            "target": "ch99_alice_alive",
                            "from_ending_survivors": "Alice",
                            "default_if_not_dead": True,
                        },
                    ],
                    "cross_chapter_exports": ["ch99_kara_alive", "ch99_alice_alive"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return chapter_path


def test_build_chapter_summary_uses_fixed_and_conditional_segments():
    summary = build_chapter_summary(
        [
            {"text": "康纳处理了人质事件。"},
            {
                "condition_variable": "n002_investigation_strategy",
                "options": {
                    "thorough": "他彻底搜查了公寓。",
                    "rush": "他直接走上阳台。",
                },
            },
            {
                "condition_variable": "_ending_id",
                "options": {
                    "ending_snipers_shot": "艾玛获救，丹尼尔被狙击手击毙。",
                },
            },
        ],
        {
            "n002_investigation_strategy": "thorough",
            "_ending_id": "ending_snipers_shot",
        },
    )

    assert summary == "康纳处理了人质事件。他彻底搜查了公寓。艾玛获救，丹尼尔被狙击手击毙。"


def test_extract_cross_chapter_state_returns_only_exported_present_keys():
    state = {
        "cop_saved_ch01": True,
        "software_instability": 2,
        "chapter_local": "ignore",
    }

    assert extract_cross_chapter_state(
        state,
        ["cop_saved_ch01", "software_instability", "missing_key"],
    ) == {
        "cop_saved_ch01": True,
        "software_instability": 2,
    }


def test_ending_payload_preserves_survivors_deaths_and_tier():
    chapter_data = {
        "endings": {
            "ending_kara_died": {
                "tier": "fatal",
                "title": "Kara Died",
                "narrative": "Kara died on the road.",
                "survivors": ["Alice"],
                "deaths": ["Kara"],
            }
        }
    }

    payload = ending_payload(chapter_data, "ending_kara_died")

    assert payload == {
        "id": "ending_kara_died",
        "title": "Kara Died",
        "narrative": "Kara died on the road.",
        "survivors": ["Alice"],
        "deaths": ["Kara"],
        "tier": "fatal",
    }


def test_apply_derived_exports_copies_state_and_derives_ending_membership():
    state = {
        "cop_saved": True,
        "connor_death_count": 0,
    }
    result = {
        "ending": {
            "survivors": ["Connor", "Emma"],
            "deaths": ["Daniel"],
        }
    }

    apply_derived_exports(
        state,
        [
            {"target": "cop_saved_ch01", "source": "cop_saved"},
            {"target": "emma_alive", "from_ending_survivors": "Emma", "default_if_not_dead": True},
            {"target": "daniel_alive", "from_ending_deaths": "Daniel", "invert": True},
        ],
        result,
    )

    assert state["cop_saved_ch01"] is True
    assert state["emma_alive"] is True
    assert state["daniel_alive"] is False


def test_apply_derived_exports_uses_derive_rule_as_boolean_condition():
    state = {
        "activity_choice": "piano",
    }

    apply_derived_exports(
        state,
        [
            {
                "target": "ch05_played_piano",
                "source": "activity_choice",
                "derive_rule": "activity_choice == piano",
            },
            {
                "target": "ch05_played_chess",
                "source": "activity_choice",
                "derive_rule": "activity_choice == chess",
            },
            {
                "target": "ch05_read_book",
                "source": "activity_choice",
                "derive_rule": "activity_choice == book",
            },
        ],
        {"ending": {}},
    )

    assert state["ch05_played_piano"] is True
    assert state["ch05_played_chess"] is False
    assert state["ch05_read_book"] is False


def test_campaign_derives_survivor_exports_from_runner_ending_payload(tmp_path):
    chapter_path = write_fatal_survivor_chapter(tmp_path)

    campaign = run_campaign(
        chapter_paths=[chapter_path],
        ai_client=ScriptedAI(),
        output_dir=tmp_path,
        dry_run=True,
    )

    assert campaign["chapters"][0]["ending_id"] == "ending_kara_died"
    assert campaign["final_cross_chapter_state"]["ch99_kara_alive"] is False
    assert campaign["final_cross_chapter_state"]["ch99_alice_alive"] is True


def test_single_chapter_run_records_no_campaign_injection_when_params_absent(tmp_path):
    result = run_experiment(
        json_path=CH03_ZH,
        ai_client=ScriptedAI(
            {
                "n001_park_exploration": "direct",
                "n002_protester_encounter": "avoid",
            }
        ),
        output_dir=tmp_path,
        dry_run=True,
    )

    assert result["config"]["cross_chapter_state_injected"] is False
    assert result["config"]["memory_summary_injected"] is False
    assert "以下是此前在这个游戏中发生的事" not in result["decisions"][0]["messages_sent"][0]["content"]


def test_campaign_run_injects_previous_chapter_summary_into_second_chapter(tmp_path):
    scripted_ai = ScriptedAI(
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
        ai_client=scripted_ai,
        output_dir=tmp_path,
        dry_run=True,
        persona_name="default",
    )

    assert campaign["config"]["chapter_count"] == 2
    assert len(campaign["chapters"]) == 2
    assert campaign["status"] == "complete"
    assert campaign["progress"] == {
        "completed": 2,
        "requested": 2,
        "next_chapter_index": None,
    }
    assert campaign["final_cross_chapter_state"]["cop_saved_ch01"] is True
    assert campaign["final_cross_chapter_state"]["connor_death_count"] == 0
    assert "菲利普斯公寓的人质事件" in campaign["full_memory_summary"]

    ch03_result_path = next(tmp_path.glob("ch03_shades_of_color_scripted_default_casual_*.json"))
    ch03_result = json.loads(ch03_result_path.read_text(encoding="utf-8"))
    first_system_message = ch03_result["decisions"][0]["messages_sent"][0]["content"]

    assert "以下是此前在这个游戏中发生的事" in first_system_message
    assert "菲利普斯公寓的人质事件" in first_system_message
    assert ch03_result["config"]["cross_chapter_state_injected"] is True
    assert ch03_result["config"]["memory_summary_injected"] is True

    campaign_files = list(tmp_path.glob("campaign_scripted_default_casual_*.json"))
    assert len(campaign_files) == 1


def test_expand_chapter_paths_expands_literal_glob_in_chapter_order():
    paths = expand_chapter_paths([str(PROJECT_ROOT / "01_json" / "zh" / "ch*.json")])

    assert len(paths) == 32
    assert Path(paths[0]).name == "ch01_the_hostage_zh.json"
    assert Path(paths[-1]).name == "ch32_battle_for_detroit_zh.json"


def test_expand_chapter_paths_preserves_explicit_path_order():
    paths = expand_chapter_paths([str(CH03_ZH), str(CH01_ZH)])

    assert paths == [str(CH03_ZH), str(CH01_ZH)]


def test_expand_chapter_paths_rejects_unmatched_pattern():
    missing = str(PROJECT_ROOT / "01_json" / "zh" / "missing*.json")

    with pytest.raises(ValueError, match="matched no chapter files"):
        expand_chapter_paths([missing])


class MetadataOnlyCLIClient(LLMClient):
    """进程内返回固定选择的 CLI 客户端：验证 campaign 元数据，不启动 claude 子进程、
    不消耗订阅额度。"""

    def __init__(self):
        super().__init__(provider="cli", cli_kind="claude", model="claude-code")
        self.resolved_model = "claude-opus-4-6"
        self.cli_version = "2.1.207"

    def choose(self, node_id, context, choices, messages):
        return {
            "choice_id": choices[0]["id"],
            "reasoning": "metadata-only test",
            "raw": json.dumps({"choice": 1, "reasoning": "metadata-only test"}),
        }


def test_cli_campaign_records_non_applicable_temperature_and_resolved_model(tmp_path):
    client = MetadataOnlyCLIClient()

    campaign = run_campaign(
        chapter_paths=[CH03_ZH],
        ai_client=client,
        output_dir=tmp_path,
        dry_run=True,
    )

    # campaign 与单章必须记同一套后端元数据：temperature 一致为 N/A (cli)，
    # 并记录实际底层模型与 CLI 版本。
    assert campaign["config"]["model"] == "claude-code"
    assert campaign["config"]["resolved_model"] == "claude-opus-4-6"
    assert campaign["config"]["backend"] == "cli"
    assert campaign["config"]["cli_version"] == "2.1.207"
    assert campaign["config"]["temperature"] == "N/A (cli)"


class FailOnChapterThreeAI(ScriptedAI):
    """ch01 正常跑完；进入 ch03（首节点 n001_park_exploration）时抛错，
    模拟长 campaign 后段中断。"""

    def choose(self, node_id, context, choices, messages):
        if node_id == "n001_park_exploration":
            raise RuntimeError("forced chapter failure")
        return super().choose(node_id, context, choices, messages)


def test_campaign_checkpoint_survives_later_chapter_failure(tmp_path):
    with pytest.raises(RuntimeError, match="forced chapter failure"):
        run_campaign(
            chapter_paths=[CH01_ZH, CH03_ZH],
            ai_client=FailOnChapterThreeAI(),
            output_dir=tmp_path,
            dry_run=True,
        )

    # 中断后仍应留下一个 status=partial 的 campaign 检查点，说明进度与已完成章节。
    campaign_files = list(tmp_path.glob("campaign_scripted_default_casual_*.json"))
    assert len(campaign_files) == 1

    checkpoint = json.loads(campaign_files[0].read_text(encoding="utf-8"))
    assert checkpoint["status"] == "partial"
    assert checkpoint["progress"] == {
        "completed": 1,
        "requested": 2,
        "next_chapter_index": 2,
    }
    assert [item["chapter"] for item in checkpoint["chapters"]] == ["ch01_the_hostage"]


def test_campaign_run_supports_mandatory_story_chapter_between_choice_chapters(tmp_path):
    ch02_zh = write_mandatory_ch02(tmp_path)
    scripted_ai = ScriptedAI(
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
        chapter_paths=[CH01_ZH, ch02_zh, CH03_ZH],
        ai_client=scripted_ai,
        output_dir=tmp_path,
        dry_run=True,
        persona_name="default",
    )

    assert campaign["config"]["chapter_count"] == 3
    assert [chapter["chapter"] for chapter in campaign["chapters"]] == [
        "ch01_the_hostage",
        "ch02_opening",
        "ch03_shades_of_color",
    ]
    assert campaign["final_cross_chapter_state"]["kara_arrived_home"] is True
    assert "卡拉被托德从商店取回" in campaign["full_memory_summary"]

    ch02_result_path = next(tmp_path.glob("ch02_opening_scripted_default_casual_*.json"))
    ch02_result = json.loads(ch02_result_path.read_text(encoding="utf-8"))
    assert ch02_result["ending"]["id"] == "ending_kara_arrived_home"
    assert ch02_result["decisions"][0]["ai_choice_id"] is None
    assert ch02_result["decisions"][0]["choices_shown"] == []


def test_campaign_records_per_chapter_token_delta_for_reused_llm_client(tmp_path):
    ch02_zh = write_mandatory_ch02(tmp_path)
    ai_client = CountingLLMClient(
        {
            "n001_park_exploration": "direct",
            "n002_protester_encounter": "avoid",
        }
    )

    campaign = run_campaign(
        chapter_paths=[CH03_ZH, ch02_zh, CH03_ZH],
        ai_client=ai_client,
        output_dir=tmp_path,
        dry_run=False,
        persona_name="default",
    )

    assert [chapter["token_usage"] for chapter in campaign["chapters"]] == [
        {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220},
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220},
    ]


def test_partial_ending_resolution_allows_unlisted_choices_to_continue():
    node = {
        "id": "n005_painting_detail",
        "type": "choice",
        "system": {
            "ending_resolution": {
                "copy_carl": {"result": "ending_the_painter"},
            }
        },
    }

    assert resolve_post_choice_result(node, "subject_identity", {}, "casual") is None


def test_ending_resolution_supports_difficulty_rules_for_regular_choices():
    node = {
        "id": "n005_escape_or_fight",
        "type": "choice",
        "system": {
            "ending_resolution": {
                "escape_window": {
                    "casual": {"result": "ending_evaded_window"},
                    "experienced": {
                        "probability_success": 0.5,
                        "success": "ending_evaded_window",
                        "failure": "ending_kara_broken",
                    },
                },
            }
        },
    }

    assert resolve_post_choice_result(node, "escape_window", {}, "casual") == "ending_evaded_window"


def test_check_rule_supports_multiple_guarded_results():
    node = {
        "id": "n008_sleep",
        "type": "choice",
        "system": {
            "ending_resolution": {
                "keep_watch": {
                    "check": (
                        "shelter_choice == motel → ending_motel | "
                        "shelter_choice == car → ending_car | "
                        "shelter_choice == squat → ending_squat"
                    ),
                },
            }
        },
    }

    assert (
        resolve_post_choice_result(node, "keep_watch", {"shelter_choice": "car"}, "casual")
        == "ending_car"
    )
