from __future__ import annotations

import json
import scripts.community_manager as community_manager
from config import load_groups


def _groups_yaml() -> str:
    return """
_shared: &shared
  tone: "プロフェッショナル"
  max_chars: 1200
  active_hours: [7, 23]
  allow_links: false
  allow_images: true
  forbidden: ["保証", "絶対", "確実"]
  signature: ""
  contact: "contact"
groups:
  - <<: *shared
    id: "100"
    name: "Manual Group"
    post_url: "https://www.facebook.com/groups/100"
    selection_order: "newest"
    enabled: true
"""


def test_strict_name_fit_rejects_irrelevant_sales_crypto_and_mlm() -> None:
    assert community_manager._strict_name_fit("不動産投資情報ラウンジ")
    assert community_manager._strict_name_fit("収益物件・一棟マンション情報交換")
    assert not community_manager._strict_name_fit("売買掲示板 自動車・トラック・重機")
    assert not community_manager._strict_name_fit("暗号資産FX投資情報交換")
    assert not community_manager._strict_name_fit("MLMビジネス友達募集")


def test_save_auto_group_is_separate_from_yaml_and_load_groups_merges_shared(tmp_path, monkeypatch) -> None:
    groups_path = tmp_path / "groups.yaml"
    auto_path = tmp_path / "data" / "auto_groups.json"
    groups_path.write_text(_groups_yaml(), encoding="utf-8")

    monkeypatch.setattr(community_manager, "GROUPS_YAML", groups_path)
    monkeypatch.setattr(community_manager, "AUTO_GROUPS_JSON", auto_path)

    before = groups_path.read_text(encoding="utf-8")
    added = community_manager._save_auto_group(
        {
            "group_id": "2217518449046952",
            "name": "不動産物件情報コミュニティ",
        }
    )
    assert added is True
    assert groups_path.read_text(encoding="utf-8") == before

    stored = json.loads(auto_path.read_text(encoding="utf-8"))
    assert stored["groups"][0]["enabled"] is True
    assert stored["groups"][0]["post_url"].endswith("/2217518449046952")

    merged = load_groups(groups_path)
    by_id = {str(group["id"]): group for group in merged}
    assert set(by_id) == {"100", "2217518449046952"}
    assert by_id["2217518449046952"]["tone"] == "プロフェッショナル"
    assert by_id["2217518449046952"]["active_hours"] == [7, 23]


def test_pipeline_busy_refuses_live_owner(tmp_path, monkeypatch) -> None:
    lock = tmp_path / "pipeline.lock"
    lock.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(community_manager, "_pid_is_running", lambda pid: pid == 12345)
    busy, reason = community_manager._pipeline_busy(lock)
    assert busy is True
    assert "active" in reason
