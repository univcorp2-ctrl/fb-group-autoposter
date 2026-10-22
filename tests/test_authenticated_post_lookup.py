from src.authenticated_post_lookup import body_matches, same_group_permalink

def test_rendered_emoji_and_whitespace_do_not_hide_the_exact_post():
    body='🏢 三崎町MKビル\n価格：55億円\n利回り：2.53%\n📩 資料請求'
    visible='サカモト ヒロシ\n 三崎町MKビル\n価格：55億円\n利回り：2.53%\n 資料請求'
    assert body_matches(body,visible)
    assert not body_matches(body,visible.replace('2.53','25.3'))
    assert not body_matches(body,visible.replace('55億','5.5億'))
    assert not body_matches(body,visible+'\n管理者の承認待ち')

def test_reconciliation_never_accepts_another_group_or_a_nonpost_link():
    assert same_group_permalink('https://www.facebook.com/groups/123/posts/456/?x=1','123') == 'https://www.facebook.com/groups/123/posts/456/'
    assert same_group_permalink('https://www.facebook.com/groups/999/posts/456/','123') is None
    assert same_group_permalink('https://example.com/groups/123/posts/456/','123') is None
