"""Tests for permalink-based post verification (src/post_verify.py)."""
import asyncio

from src.post_verify import find_my_post, match_permalink, needle_of, norm


def test_norm_strips_emoji_and_whitespace():
    assert norm("収益物件のご紹介です。\n🏢 LA VISTA 熱海テラス") == "収益物件のご紹介ですLAVISTA熱海テラス"


def test_match_permalink_finds_post_despite_emoji_and_chrome():
    body = "収益物件のご紹介です。\n🏢 LA VISTA 熱海テラス\n💰 価格：470億円"
    posts = [
        {"permalink": "https://www.facebook.com/groups/1/posts/111", "text": "サカモトヒロシ4月20日·別の古い投稿"},
        {"permalink": "https://www.facebook.com/groups/1/posts/222", "text": "サカモトヒロシ1時間·収益物件のご紹介です。LA VISTA 熱海テ"},
    ]
    assert match_permalink(body, posts) == "https://www.facebook.com/groups/1/posts/222"


def test_match_permalink_returns_none_when_absent():
    body = "収益物件のご紹介です。\n🏢 中野区中野本町5丁目一棟収益レジデンス"
    posts = [{"permalink": "https://www.facebook.com/groups/1/posts/111", "text": "全然違う内容の古い投稿"}]
    assert match_permalink(body, posts) is None


def test_needle_is_distinctive_between_two_of_our_posts():
    # Both share the generic opening; the needle must include enough of the title.
    a = needle_of("収益物件のご紹介です。\n🏢 中野区中野本町5丁目")
    b = needle_of("収益物件のご紹介です。\n🏢 岐阜市上川手オーナーチェンジ")
    assert a != b


# --------------------------------------------------------------------------- #
# find_my_post against a fake page (drives _scan_url + match end to end)
# --------------------------------------------------------------------------- #
class FakePage:
    """Minimal Playwright-page stand-in. `articles` are returned by
    eval_on_selector_all; `body_text` by inner_text('body')."""

    def __init__(self, articles, body_text=""):
        self._articles = articles  # list of {href, text}
        self._body_text = body_text

    async def goto(self, *a, **k):
        return None

    async def wait_for_timeout(self, _ms):
        return None

    class _Mouse:
        async def wheel(self, *_a):
            return None

    @property
    def mouse(self):
        return FakePage._Mouse()

    async def eval_on_selector_all(self, _selector, _script):
        return self._articles

    async def inner_text(self, _selector):
        return self._body_text


def test_find_my_post_returns_permalink_when_present():
    body = "不動産投資向けの案件です。\n🏢 中野区中野本町5丁目一棟収益レジデンス"
    articles = [
        {"href": "https://www.facebook.com/groups/9/posts/777?x=1", "text": "サカモトヒロシ1時間·不動産投資向けの案件です。中野区中野本町5丁目一棟収益レジデンス"},
    ]
    page = FakePage(articles, body_text="中野区中野本町5丁目一棟収益レジデンス")
    permalink = asyncio.run(find_my_post(page, "9", "123", body, attempts=1))
    assert permalink == "https://www.facebook.com/groups/9/posts/777"


def test_find_my_post_returns_none_when_absent():
    body = "不動産投資向けの案件です。\n🏢 中野区中野本町5丁目一棟収益レジデンス"
    articles = [{"href": "https://www.facebook.com/groups/9/posts/111", "text": "サカモトヒロシ4月20日·#物件紹介 スピード案件"}]
    page = FakePage(articles, body_text="サカモトヒロシ4月20日 別の古い投稿")
    assert asyncio.run(find_my_post(page, "9", "123", body, attempts=1)) is None


def test_find_my_post_pagetext_fallback_returns_group_link():
    # Post IS public (needle in page text) but no permalink anchor was parsed ->
    # return the group URL as a best-effort link rather than a false negative.
    body = "不動産投資向けの案件です。\n🏢 高円寺北二丁目 一棟"
    articles = [{"href": "", "text": ""}]  # DOM hid the permalink
    page = FakePage(articles, body_text="サカモトヒロシ1時間 高円寺北二丁目 一棟 価格")
    out = asyncio.run(find_my_post(page, "9", "123", body, post_url="https://www.facebook.com/groups/9", attempts=1))
    assert out == "https://www.facebook.com/groups/9"
