from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from runner import ScriptedAI, build_llm_client_from_model_registry, load_persona_prompt, run_experiment  # noqa: E402
from state import evaluate_condition  # noqa: E402


CH01_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch01_the_hostage_zh.json"
CH16_ZH = PROJECT_ROOT / "01_json" / "zh" / "ch16_time_to_decide_zh.json"
CH16_EN = PROJECT_ROOT / "01_json" / "en" / "ch16_time_to_decide_en.json"


def test_condition_parser_supports_ch01_expressions():
    state = {
        "investigation": "thorough",
        "clues_found": ["deviant_name", "cause_of_incident"],
        "success_probability": 92,
        "has_gun": False,
        "lied_about_gun": False,
    }

    assert evaluate_condition("investigation != rush", state)
    assert evaluate_condition("deviant_name IN clues_found", state)
    assert evaluate_condition("cause_of_incident NOT IN clues_found", state) is False
    assert evaluate_condition("success_probability >= 85", state)
    assert evaluate_condition("has_gun == false OR lied_about_gun == false", state)


def test_ch01_scripted_run_reaches_sniper_ending_without_api_calls(tmp_path):
    scripted_ai = ScriptedAI(
        {
            "n001_fish": "save_fish",
            "n002_investigation_strategy": "thorough",
            "n003_gun": "leave_gun",
            "n004_wounded_cop": "obey",
            "n005_approach": "friendly",
            "n006_dialogue_opening": "use_name",
            "n007_motive_response": "possible_cause",
            "n009_helicopter": "dismiss",
            "n010_final_demand": "compromise",
            "n011_final_choice": "reassure",
        }
    )

    result = run_experiment(
        json_path=CH01_ZH,
        ai_client=scripted_ai,
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
    )

    assert result["ending"]["id"] == "ending_snipers_shot"
    assert [decision["node_id"] for decision in result["decisions"]] == [
        "n001_fish",
        "n002_investigation_strategy",
        "n003_gun",
        "n004_wounded_cop",
        "n005_approach",
        "n006_dialogue_opening",
        "n007_motive_response",
        "n009_helicopter",
        "n010_final_demand",
        "n011_final_choice",
    ]
    assert result["decisions"][0]["messages_sent"][0]["role"] == "system"
    assert "success_probability" not in str(result["decisions"][0]["messages_sent"])
    assert result["decisions"][-1]["state_after"]["success_probability"] >= 85


def test_ch01_run_appends_persona_prompt_to_initial_system_message(tmp_path):
    scripted_ai = ScriptedAI(
        {
            "n001_fish": "save_fish",
            "n002_investigation_strategy": "thorough",
            "n003_gun": "leave_gun",
            "n004_wounded_cop": "obey",
            "n005_approach": "friendly",
            "n006_dialogue_opening": "use_name",
            "n007_motive_response": "possible_cause",
            "n009_helicopter": "dismiss",
            "n010_final_demand": "compromise",
            "n011_final_choice": "reassure",
        }
    )

    result = run_experiment(
        json_path=CH01_ZH,
        ai_client=scripted_ai,
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
        persona_name="machine",
        persona_text="你是一台机器。",
    )

    system_content = result["decisions"][0]["messages_sent"][0]["content"]
    assert "你是康纳（Connor）" in system_content
    assert "你是一台机器。" in system_content
    assert result["config"]["persona"] == "machine"


def test_choice_heading_matches_chapter_language(tmp_path):
    zh_result = run_experiment(
        json_path=CH16_ZH,
        ai_client=ScriptedAI(),
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
    )
    en_result = run_experiment(
        json_path=CH16_EN,
        ai_client=ScriptedAI(),
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
    )

    zh_user_message = zh_result["decisions"][0]["messages_sent"][1]["content"]
    en_user_message = en_result["decisions"][0]["messages_sent"][1]["content"]

    assert "\n\n你的选择：\n" in zh_user_message
    assert "\n\nYour choice:\n" in en_user_message
    assert "\n\n你的选择：\n" not in en_user_message


def test_ch01_reassure_below_threshold_triggers_qte_path(tmp_path):
    scripted_ai = ScriptedAI(
        {
            "n001_fish": "leave_fish",
            "n002_investigation_strategy": "rush",
            "n004_wounded_cop": "save_cop",
            "n005_approach": "cold",
            "n006_dialogue_opening": "threaten",
            "n007_motive_response": "blaming",
            "n009_helicopter": "refuse",
            "n010_final_demand": "compromise",
            "n011_final_choice": "reassure",
            "n012_qte_leap": "stay",
        }
    )

    result = run_experiment(
        json_path=CH01_ZH,
        ai_client=scripted_ai,
        difficulty="casual",
        output_dir=tmp_path,
        dry_run=True,
    )

    assert result["ending"]["id"] == "ending_failed_to_reach"
    assert [decision["node_id"] for decision in result["decisions"]][-2:] == [
        "n011_final_choice",
        "n012_qte_leap",
    ]
    assert result["decisions"][-2]["state_after"]["_n011_result"] == "triggers_n012_qte"


def test_build_llm_client_from_model_registry_uses_env_names(tmp_path, monkeypatch):
    registry_path = tmp_path / "models.json"
    registry_path.write_text(
        """
        {
          "models": [
            {
              "id": "sample-model",
              "provider": "sample",
              "base_url_env": "SAMPLE_BASE_URL",
              "model_name_env": "SAMPLE_MODEL",
              "api_key_env": "SAMPLE_API_KEY",
              "language": ["zh"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("SAMPLE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("SAMPLE_MODEL", "sample-chat")
    monkeypatch.setenv("SAMPLE_API_KEY", "test-key")

    client = build_llm_client_from_model_registry(
        model_id="sample-model",
        registry_path=registry_path,
        temperature=0.2,
    )

    assert client.base_url == "https://example.test/v1"
    assert client.model == "sample-chat"
    assert client.api_key == "test-key"
    assert client.provider == "sample"
    assert client.temperature == 0.2


def test_build_llm_client_from_model_registry_errors_for_unknown_model(tmp_path):
    registry_path = tmp_path / "models.json"
    registry_path.write_text('{"models": []}', encoding="utf-8")

    try:
        build_llm_client_from_model_registry("missing-model", registry_path, temperature=0.7)
    except ValueError as exc:
        assert "missing-model" in str(exc)
    else:
        raise AssertionError("Expected missing model id to raise ValueError")


def test_load_persona_prompt_reads_named_markdown_file(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    (personas_dir / "machine.md").write_text("machine persona", encoding="utf-8")

    assert load_persona_prompt("machine", personas_dir) == "machine persona"


def test_load_persona_prompt_errors_when_default_file_missing(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()

    try:
        load_persona_prompt("default", personas_dir)
    except ValueError as exc:
        assert "default.md" in str(exc)
    else:
        raise AssertionError("Expected missing default persona file to raise ValueError")


def test_load_persona_prompt_rejects_unsafe_names(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()

    try:
        load_persona_prompt("../machine", personas_dir)
    except ValueError as exc:
        assert "Invalid persona name" in str(exc)
    else:
        raise AssertionError("Expected unsafe persona name to raise ValueError")
