# Deep Verification

## 目的

通常の単体テストに加えて、設定不備、group policy、DB冪等性、承認ゲート、投稿前preflight、dry-run pipeline、ランダム生成不変条件を何十回も反復検証する。

## コマンド

```powershell
python scripts/run_tests_10.py
python scripts/run_tests_50.py
python scripts/run_tests_50.py --rounds 100
```

各roundで以下を実行する。

```powershell
python -m ruff check .
python -m pytest -q
```

## 検証範囲

- `group_rules.py`: URL除去、禁止語除去、署名冪等、文字数制限
- `property_schema.py`: 正規化、ID安定性、list変換
- `generator.py`: API障害時fallback、数値不改変、group別variation
- `queue_db.py`: UNIQUE制約、状態遷移、stale recovery、circuit breaker
- `approval.py`: AUTO_APPROVE、degraded強制承認待ち
- `poster.py`: daily limit、active hours、duplicate guard、dry-run投稿モック
- `session.py`: login/checkpoint検知入口
- `orchestrator.py`: dry-run selftest全体通過

## 実投稿テストについて

自動CIでは実投稿しない。実投稿を伴うE2EはREADMEの手順どおり、Hiroの検証用グループで1回だけ実施する。
