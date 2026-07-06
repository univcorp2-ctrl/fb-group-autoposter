from src.facebook_metrics import extract_metric_counts, parse_compact_number


def test_parse_compact_number() -> None:
    assert parse_compact_number("1.2万") == 12000
    assert parse_compact_number("2.5K") == 2500
    assert parse_compact_number("1,234") == 1234


def test_extract_japanese_metrics() -> None:
    result = extract_metric_counts("リアクション: 18 コメント 4件 シェア 2件 表示 1.2万回")
    assert result == {"reactions": 18, "comments": 4, "shares": 2, "views": 12000}


def test_extract_english_metrics() -> None:
    result = extract_metric_counts("25 reactions 7 comments 3 shares 1.5K views")
    assert result == {"reactions": 25, "comments": 7, "shares": 3, "views": 1500}
