# 検証結果

2026-10-30 / JSON・JSONLの最初の実装。

- 環境: Python 3.12.14; Pydantic 2.14.2; portalocker 3.2.0; pytest 9.2.0
- pytest: 43件成功。
- example.py: 単一モデル、混在モデル、dict一覧の保存と復元に成功。
- Pyright: 0 errors / 0 warnings。
- 誤入力用typecheck/negative.py: 想定するreportArgumentTypeを3件検出。
- 単一モデル・混在モデル・dictの返却型と、isinstanceによる型の絞り込みをassert_typeで確認。
- Windows上の同時追記（スレッド、新規作成、2プロセス）、ロック取得失敗、末尾破損、置換失敗を検証。

Pylanceの画面操作による検証は実施していない。同系のPyrightで静的型を検証した。
Pydanticの最低対応版2.7と、Windows以外のOSではまだ実行検証していない。
CSV / YAML / 独自テキスト / Waveform / Excel保存との結合は未実装・未検証。
直接追記中のプロセス強制終了による障害注入は未実施。既に破損した末尾を拒否するテストは実施した。
