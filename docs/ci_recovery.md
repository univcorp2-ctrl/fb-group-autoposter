# CI Recovery

`.github/workflows/ci.yml` の作成がGitHub API 404で拒否される場合、workflow作成権限が不足している可能性がある。

このrepoには同じ内容を `ci/ci.yml` として保存している。権限復旧後、内容を `.github/workflows/ci.yml` に配置すれば50回反復検証CIが動く。

## 期待されるCI内容

- checkout
- Python 3.11 setup
- dependencies install
- `python scripts/run_tests_50.py --rounds 50`
- screenshots/logs artifact upload

## 現状

通常ファイルのcommitは成功している。拒否されているのは `.github/workflows/*` の作成のみ。
