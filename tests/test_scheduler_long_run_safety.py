from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_posting_tasks_allow_long_humanized_run_without_changing_other_limits():
    source = (ROOT / "scripts" / "install_windows_tasks.ps1").read_text(encoding="utf-8")
    for name in ("Morning", "Midday", "Afternoon", "Evening"):
        line = next(line for line in source.splitlines() if f"FBAutoposter-{name}'" in line)
        assert "-ExecutionHours 8" in line
    assert "[int]$ExecutionHours = 1" in source
    assert "New-TimeSpan -Minutes 10" in source
    assert ".venv\\Scripts\\pythonw.exe" in source
    assert "-Hidden" in source


def test_runtime_repair_keeps_hidden_launcher_and_long_posting_limit():
    source = (ROOT / "scripts" / "repair_windows_runtime.ps1").read_text(encoding="utf-8")
    for name in ("Morning", "Midday", "Afternoon", "Evening"):
        line = next(line for line in source.splitlines() if f"FBAutoposter-{name}'" in line)
        assert "-ExecutionHours 8" in line
    assert "[int]$ExecutionHours=1" in source
    assert "-WindowStyle Hidden" in source
    assert "-Hidden" in source


def test_one_shot_task_repair_keeps_tasks_hidden_and_long_running():
    source = (ROOT / "scripts" / "repair_posting_tasks.ps1").read_text(encoding="utf-8")
    assert "-ExecutionTimeLimit (New-TimeSpan -Hours 8)" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "-Hidden" in source
    assert ".venv\\Scripts\\pythonw.exe" in source

def test_community_manager_task_is_hidden_and_bounded():
    source = (ROOT / "scripts" / "install_windows_tasks.ps1").read_text(encoding="utf-8")
    assert "FBAutoposter-CommunityManager" in source
    assert "scripts\\community_manager.py" in source
    assert "-At '06:20'" in source
    assert "New-TimeSpan -Minutes 20" in source
    assert "New-TimeSpan -Minutes 30" in source
    assert "-MultipleInstances IgnoreNew" in source
    assert "-Hidden" in source
