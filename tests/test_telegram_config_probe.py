from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

from src.telegram_config_probe import probe_telegram_config


TOKEN = "123456:ABCdef-ghI_jklMNopQRstuVWXyz"
CHAT_ID = "-1001234567890"


def _workbook(path, *, chat_id=CHAT_ID, token=TOKEN):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Telegrams"
    sheet["A2"] = chat_id
    sheet["B8"] = token
    workbook.save(path)


def _env(path, *, chat_id=CHAT_ID, token=TOKEN):
    path.write_text(
        f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_ID={chat_id}\nUNRELATED_SECRET=do-not-return\n",
        encoding="utf-8",
    )


def test_probe_confirms_matching_env_and_workbook_without_returning_values(tmp_path):
    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    _env(env_path)
    _workbook(workbook_path)

    result = probe_telegram_config(env_path, workbook_path)

    assert result == {
        "env_configured": True,
        "workbook_configured": True,
        "token_match": True,
        "chat_id_match": True,
        "role": "same_credentials",
        "reason_codes": [],
    }
    assert TOKEN not in repr(result)
    assert CHAT_ID not in repr(result)


def test_probe_reports_safe_mismatch_code_only(tmp_path):
    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    _env(env_path)
    _workbook(workbook_path, token="999999:other_BotFatherToken")

    result = probe_telegram_config(env_path, workbook_path)

    assert result["role"] == "different_bot"
    assert result["token_match"] is False
    assert result["reason_codes"] == ["token_mismatch"]
    assert TOKEN not in repr(result)


def test_probe_extracts_one_token_from_botfather_style_prose(tmp_path):
    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    _env(env_path)
    _workbook(workbook_path, token=f"Use this token for the HTTP API:\n{TOKEN}\nKeep it secure.")

    result = probe_telegram_config(env_path, workbook_path)

    assert result["role"] == "same_credentials"
    assert result["token_match"] is True
    assert TOKEN not in repr(result)


def test_probe_rejects_ambiguous_botfather_tokens_without_returning_them(tmp_path):
    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    other_token = "654321:ZYXwvu-tsR_qponMLKJihgFEDCBA"
    _env(env_path)
    _workbook(workbook_path, token=f"{TOKEN}\n{other_token}")

    result = probe_telegram_config(env_path, workbook_path)

    assert result["role"] == "incomplete"
    assert result["reason_codes"] == ["workbook_token_ambiguous"]
    assert TOKEN not in repr(result)
    assert other_token not in repr(result)


def test_probe_missing_inputs_returns_safe_reason_codes(tmp_path):
    result = probe_telegram_config(tmp_path / ".env", tmp_path / "private.xlsx")

    assert result["role"] == "incomplete"
    assert result["reason_codes"] == ["env_file_missing", "workbook_file_missing"]


def test_delivery_check_script_prints_only_safe_probe_json(tmp_path, capsys):
    from scripts.check_telegram_delivery import main

    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    _env(env_path)
    _workbook(workbook_path)

    assert main(env_path=env_path, workbook_path=workbook_path) == 0

    output = capsys.readouterr().out
    assert '"role": "same_credentials"' in output
    assert TOKEN not in output
    assert CHAT_ID not in output


def test_delivery_check_script_runs_directly_from_repo_root(tmp_path):
    env_path = tmp_path / ".env"
    workbook_path = tmp_path / "private.xlsx"
    _env(env_path)
    _workbook(workbook_path)
    repo_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_telegram_delivery.py",
            "--env-path",
            str(env_path),
            "--workbook-path",
            str(workbook_path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"role": "same_credentials"' in completed.stdout
    assert TOKEN not in completed.stdout
    assert CHAT_ID not in completed.stdout
