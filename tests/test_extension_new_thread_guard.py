from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = (ROOT / "extension" / "content.js").read_text(encoding="utf-8")
BACKGROUND = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")


def test_existing_post_and_comment_contexts_are_rejected():
    assert "function isInsideExistingPost" in CONTENT
    assert "closest('[role=\"article\"]')" in CONTENT
    assert 'aria-label*="コメント"' in CONTENT
    assert 'aria-label*="返信"' in CONTENT
    assert 'aria-label*="Comment"' in CONTENT
    assert 'aria-label*="Reply"' in CONTENT


def test_editor_and_post_button_are_scoped_to_safe_new_thread():
    assert "function isSafeNewThreadElement" in CONTENT
    assert 'el.closest("#fbgp-panel")' in CONTENT
    assert "function findComposerScope(editable)" in CONTENT
    assert "function findPostButton(editable)" in CONTENT
    assert "findPostButton(editable)" in CONTENT
    assert "const scope = document.querySelector('div[role=\"dialog\"]') || document;" not in CONTENT


def test_do_post_returns_to_group_top_and_never_falls_back_to_comment_editor():
    assert 'window.scrollTo({ top: 0, behavior: "instant" })' in CONTENT
    assert "コメント/返信欄への投稿は禁止しています" in CONTENT
    assert "安全な新規投稿本文欄が見つかりません" in CONTENT


def test_background_only_closes_marked_automation_tabs():
    assert 'fbautoposter_task=' in BACKGROUND
    assert 'let stillOwned = (tab?.url || "").includes(marker)' in BACKGROUND
    assert 'if (stillOwned) await chrome.tabs.remove(state.tabId)' in BACKGROUND


def test_new_post_submit_state_must_be_active_before_click():
    assert "function findPostButtonCandidate(editable)" in CONTENT
    assert "COMPOSER_STATE_NOT_COMMITTED" in CONTENT
    assert 'requireActiveButton: post || task?.action === "layout_check"' in CONTENT
    assert "if (pasted && (!requireActiveButton || findPostButton(editable)))" in CONTENT
    assert "if (paragraphLayout && (!requireActiveButton || findPostButton(editable)))" in CONTENT
    assert 'if (task?.task_id) await reportStage(task.task_id, "click_started")' in CONTENT
    assert "if (!btn) throw new Error" in CONTENT


def test_preview_diagnoses_button_without_clicking():
    assert "const buttonDiagnostics = describePostButton(editable)" in CONTENT
    assert "mode=" in CONTENT
    assert 'if (task?.action === "layout_check")' in CONTENT
    assert "clearEditable(editable);" in CONTENT
