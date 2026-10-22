import asyncio
from src.thread_context import read_recent_thread_text
from src.authenticated_chrome import AUTOMATION_PAGE_TAG


def test_encrypted_dm_history_is_read_from_the_conversation_panel():
    class Locator:
        def __init__(self, page): self.page = page
        @property
        def first(self): return self
        async def count(self): return 1
        async def inner_text(self, **kwargs):
            return 'Hiroaki Kobayashi 商流教えてください' if '/e2ee/t/' in self.page.url else 'チャットが選択されていません'
    class Page:
        url = ''
        async def evaluate(self, script): return AUTOMATION_PAGE_TAG
        async def goto(self, url, **kwargs): self.url = url
        async def wait_for_timeout(self, milliseconds): pass
        def get_by_text(self, *args, **kwargs): return Locator(self)
        def locator(self, selector): return Locator(self)
    page = Page()
    history = asyncio.run(read_recent_thread_text(page, '1390317282929328', 'Hiroaki Kobayashi'))
    assert '商流教えてください' in history
