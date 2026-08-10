# Latest core-test diagnostic

```text
........................................................................ [ 28%]
........................................................................ [ 56%]
............................F
=================================== FAILURES ===================================
_________________ test_readme_links_shared_analytics_surfaces __________________

    def test_readme_links_shared_analytics_surfaces() -> None:
        readme = (
            __import__("pathlib")
            .Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("README.md")
            .read_text(encoding="utf-8")
        )
        for required in (
            "Facebook投稿分析",
            "https://estateboard.pages.dev/facebook-analytics/",
            "https://github.com/univcorp2-ctrl/EstateBoard",
            "https://github.com/univcorp2-ctrl/fb-group-autoposter",
            "ANALYTICS_SYNC_ENABLED=true",
            "open-facebook-analytics.cmd",
        ):
>           assert required in readme
E           AssertionError: assert 'Facebook投稿分析' in '# Facebook Group Property Autoposter\n\nEstateBoardの最新物件を選び、グループごとの重複・日次上限・投稿時間を守りながら、ログイン済みFacebookブラウザへ画像付きで投稿するWin...ite permalinkを照合します。\n\n詳細は [docs/setup.md](docs/setup.md) と [docs/architecture.md](docs/architecture.md) を参照してください。\n'

tests/test_open_analytics_dashboard.py:69: AssertionError
=========================== short test summary info ============================
FAILED tests/test_open_analytics_dashboard.py::test_readme_links_shared_analytics_surfaces - AssertionError: assert 'Facebook投稿分析' in '# Facebook Group Property Autoposter\n\nEstateBoardの最新物件を選び、グループごとの重複・日次上限・投稿時間を守りながら、ログイン済みFacebookブラウザへ画像付きで投稿するWin...ite permalinkを照合します。\n\n詳細は [docs/setup.md](docs/setup.md) と [docs/architecture.md](docs/architecture.md) を参照してください。\n'
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
```
