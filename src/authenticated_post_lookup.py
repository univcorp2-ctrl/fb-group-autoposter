"""Read the rendered own-posts list; never submit or retry a post."""
import re
import unicodedata
from urllib.parse import urlparse


def semantic_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value)
                   if not c.isspace() and unicodedata.category(c) not in {'So','Sk','Cf'}
                   and c not in '\ufe0e\ufe0f')


def body_matches(body, article):
    if re.search(r'管理者の承認|承認待ち|pending approval|awaiting approval', article, re.I):
        return False
    expected = semantic_text(body)
    return bool(expected) and expected in semantic_text(article)


def same_group_permalink(href, group_id):
    url = urlparse(href)
    if url.hostname != 'www.facebook.com':
        return None
    match = re.fullmatch(r'/groups/'+re.escape(str(group_id))+r'/(?:posts|permalink)/(\d+)/?',url.path)
    return 'https://www.facebook.com'+url.path.rstrip('/')+'/' if match else None


async def lookup_published_post(page, task):
    group_id = str(task['group_id'])
    await page.goto('https://www.facebook.com/groups/'+group_id+'/my_posted_content',
                    wait_until='domcontentloaded',timeout=45000)
    await page.wait_for_timeout(3500)
    if '/login' in page.url or '/checkpoint' in page.url:
        return {'status':'uncertain','error':'verification_auth_required'}
    links = await page.locator('a[href]').evaluate_all('(els)=>els.map(e=>e.href)')
    candidates = list(dict.fromkeys(link for href in links
                      if (link := same_group_permalink(href,group_id))))[:12]
    for link in candidates:
        await page.goto(link,wait_until='domcontentloaded',timeout=45000)
        await page.wait_for_timeout(2000)
        # Facebook truncates long property posts. Expanding text is read-only.
        for label in ['さらに表示','もっと見る','See more']:
            buttons = page.get_by_role('button',name=label,exact=True)
            for button in (await buttons.all())[:3]:
                if await button.is_visible():
                    await button.click()
                    await page.wait_for_timeout(300)
        articles = await page.locator('[role="article"]').all_inner_texts()
        if any(body_matches(task['body'],article) for article in articles):
            return {'status':'posted','permalink':link,'verification':'own_posts_dom_full_body'}
    return {'status':'uncertain','error':'own_posts_dom_full_body_not_found'}
