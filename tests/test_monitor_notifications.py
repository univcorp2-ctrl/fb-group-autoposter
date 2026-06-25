"""Tests for FB-notification relevance filtering (the noise filter)."""
from scripts.monitor_notifications import _classify, _digest


def test_classify_keeps_reactions_on_our_posts():
    assert _classify("中谷さん、他2人が、不動産取引の情報交換でのあなたの投稿に「いいね！」しました") == "reaction"


def test_classify_keeps_comments_on_our_posts():
    assert _classify("Seiyaさんが不動産取引の情報交換であなたの投稿にコメントしました。") == "comment"


def test_classify_keeps_reply_to_our_comment():
    assert _classify("田中さんがあなたのコメントに返信しました") == "comment"


def test_classify_drops_friend_requests_and_group_noise():
    assert _classify("鈴木さんから友達リクエストが届いています") is None
    assert _classify("小原さんが不動産投資セミナーに投稿しました。") is None
    # A comment on a photo you merely FOLLOW is not your post -> dropped.
    assert _classify("平林さん、他5人が新築不動産投資の学校であなたがフォローしている写真にコメントしました") is None
    # A mention in an unrelated group is not your post -> dropped.
    assert _classify("Plantsさんがサボテン即売会のコメントであなたと他の人をメンションしました") is None


def test_digest_is_stable_and_distinct():
    a = _digest("text one", "https://x/1")
    assert a == _digest("text one", "https://x/1")
    assert a != _digest("text two", "https://x/1")
