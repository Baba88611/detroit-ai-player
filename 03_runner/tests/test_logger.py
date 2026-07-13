from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from logger import write_campaign_result, write_result  # noqa: E402


def test_write_result_prints_saved_path_to_stderr(tmp_path, capsys):
    result = {
        "experiment_id": "12345678-0000-0000-0000-000000000000",
        "config": {
            "chapter": "ch01_the_hostage",
            "model": "test-model",
            "persona": "default",
            "difficulty": "casual",
        },
    }

    saved = write_result(result, tmp_path)
    captured = capsys.readouterr()

    assert saved.exists()
    assert f"Saved chapter result: {saved.resolve()}" in captured.err


def test_write_campaign_result_prints_saved_path_and_status(tmp_path, capsys):
    result = {
        "campaign_id": "87654321-0000-0000-0000-000000000000",
        "status": "complete",
        "config": {
            "model": "test-model",
            "persona": "default",
            "difficulty": "casual",
        },
    }

    saved = write_campaign_result(result, tmp_path)
    captured = capsys.readouterr()

    assert saved.exists()
    assert f"Saved campaign result [complete]: {saved.resolve()}" in captured.err
