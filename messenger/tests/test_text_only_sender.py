"""Exercise the real send flow against a synthetic browser; no external messages."""
import asyncio
from types import SimpleNamespace

from scripts import send_one_playwright_reply as sender


def test_text_only_reply_does_not_treat_browser_as_pdf(monkeypatch, tmp_path):
    import playwright.async_api
    from src import direct_thread_guard, messenger_attachment

    incoming = '池袋の物件はまだ販売中ですか？'
    reply = 'お問い合わせありがとうございます。販売状況は現在の資料では確認できないため、断定を控えます。'
    editor = SimpleNamespace(text='')
    clicks = []
    gates = []

    class Locator:
        @property
        def first(self):
            return self

        async def count(self):
            return 0

        async def inner_text(self, **_):
            return incoming + (reply if clicks else '')

    class Button:
        async def click(self, **_):
            clicks.append('send')
            editor.text = ''

    class Page:
        url = 'https://www.messenger.com/t/123456789'

        async def goto(self, url, **_):
            self.url = url

        async def wait_for_timeout(self, _):
            pass

        def locator(self, _):
            return Locator()

        def get_by_role(self, *_, **__):
            return Locator()

    page = Page()

    class Client:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            pass

    async def attach(*_):
        return SimpleNamespace(context=object())  # deliberately has no PDF file_path

    async def select(*_):
        return page

    async def scan(*_, **__):
        return ({'name': '検証用', 'preview': incoming if not clicks else 'あなた:' + reply},
                SimpleNamespace(needs_reply=not clicks, reason='incoming' if not clicks else 'already_replied'), 1)

    async def yes(*_):
        return True

    async def visible(_, selectors):
        return editor if selectors is sender.COMPOSER_SELECTORS else Button()

    async def text(value):
        return value.text

    async def fill(_, value, content):
        value.text = content

    async def forbidden_pdf(*_, **__):
        raise AssertionError('No attachment API is permitted for a text-only reply')

    monkeypatch.setattr(playwright.async_api, 'async_playwright', Client)
    monkeypatch.setattr(sender, 'attach_authenticated_context', attach)
    monkeypatch.setattr(sender, 'select_messenger_page', select)
    monkeypatch.setattr(sender, '_scan_exact_thread', scan)
    monkeypatch.setattr(sender, '_any_exact_text_visible', yes)
    monkeypatch.setattr(direct_thread_guard, 'assert_one_to_one_thread', yes)
    monkeypatch.setattr(sender, '_first_visible', visible)
    monkeypatch.setattr(sender, '_editor_text', text)
    monkeypatch.setattr(sender, '_set_editor_text', fill)
    monkeypatch.setattr(sender, '_restore_editor', fill)
    monkeypatch.setattr(sender, '_assert_global_send_guard', lambda *a, **kw: gates.append(kw))
    monkeypatch.setattr(messenger_attachment, 'stage_verified_pdf', forbidden_pdf)
    monkeypatch.setattr(messenger_attachment, 'attachment_visible_after_send', forbidden_pdf)
    args = SimpleNamespace(thread_id='123456789', target_name='検証用', scan_limit=40, send=True, auto_claim='synthetic')
    result = asyncio.run(sender._run_browser(SimpleNamespace(data_dir=tmp_path), args,
        {'last_message': incoming, 'url': page.url, 'material': None}, reply, {}))
    assert result['sent'] is True
    assert clicks == ['send']
    assert len(gates) == 2 and gates[-1]['consume'] is True
