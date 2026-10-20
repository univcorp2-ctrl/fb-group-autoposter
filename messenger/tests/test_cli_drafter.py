from types import SimpleNamespace

import pytest

from src import cli_drafter, drafter


def test_codex_cli_uses_stdin_and_result_file(monkeypatch):
    monkeypatch.setattr(cli_drafter, "resolve_executable", lambda p: "codex.cmd")
    def fake_run(argv, **kwargs):
        assert argv[0] == "codex.cmd" and argv[-1] == "-"
        assert "--output-last-message" in argv
        assert "顧客" in kwargs["input"] or "受信文" in kwargs["input"]
        from pathlib import Path
        Path(argv[argv.index("--output-last-message") + 1]).write_text("お問い合わせありがとうございます。お探しのエリアをお伺いできますか？", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(cli_drafter.subprocess, "run", fake_run)
    text=cli_drafter.generate_via_cli("codex","山田","物件の資料はありますか？")
    assert "お問い合わせ" in text


def test_claude_cli_does_not_send_or_execute_tools(monkeypatch):
    monkeypatch.setattr(cli_drafter, "resolve_executable", lambda p: "claude.exe")
    def fake_run(argv, **kwargs):
        assert argv[:2] == ["claude.exe", "--print"]
        assert "--tools" in argv and argv[argv.index("--tools")+1] == ""
        return SimpleNamespace(returncode=0, stdout="ありがとうございます。ご希望エリアを教えてください。", stderr="")
    monkeypatch.setattr(cli_drafter.subprocess, "run", fake_run)
    assert "ありがとうございます" in cli_drafter.generate_via_cli("claude","佐藤","購入希望")


def test_cli_failure_safely_falls_back_to_template(monkeypatch):
    monkeypatch.setenv("MESSENGER_DRAFT_PROVIDER","codex")
    monkeypatch.setattr(cli_drafter, "generate_via_cli", lambda *a, **kw: None)
    result=drafter.build_draft("田中","物件の資料を見たいです")
    assert "お問い合わせ" in result and "下書き" in result


def test_unexpected_provider_rejected():
    with pytest.raises(ValueError):
        cli_drafter.generate_via_cli("unsafe","山田","質問")
