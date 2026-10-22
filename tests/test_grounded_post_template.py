from src.generator import fallback_body


def test_template_does_not_infer_statutory_life_or_vacant_delivery():
    prop={'title':'検証物件','location':'東京都港区','price':'10,000万円','yield_pct':'7.2%',
          'structure':'RC造 4階建','access':'検証駅 徒歩5分','highlights':['一棟マンション']}
    body=fallback_body(prop,{'max_chars':1200})
    assert '法定耐用年数' not in body
    land=fallback_body({**prop,'title':'検証土地','yield_pct':'—','highlights':['土地']},{'max_chars':1200})
    assert '空渡し' not in land
