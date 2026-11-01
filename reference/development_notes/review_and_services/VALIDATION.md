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

## コーディングルール反映後の再検証

- 内部のメンバ変数を非公開化し、参照が必要な情報だけ読み取り専用propertyで公開。
- 設定用frozen dataclassと業務モデルのフィールドは、利用側が指定する公開項目として維持。
- 引数名をbase_directory / serializers_by_extension / lock_timeout_secondsへ変更。
- 実装・テスト・実行例のdocstring直後の空白と、None戻り値注釈の省略を確認。
- 構文木で12個のPythonファイルを点検し、実装の公開インスタンス属性がないことを確認。
- pytest: 43件成功。実行例も成功。
- Pyright: 0 errors / 0 warnings。None戻り値の関数は推論で型を保持。
- 誤入力用typecheck/negative.pyは、想定するreportArgumentTypeを3件検出。
- 今後の実装に適用するルールをAGENTS.mdへ記録。

## 目的・流れの説明を補った後の確認

- 5個の実装ファイルでクラスの役割、委譲先、重要なメソッドの処理順と判断理由を補足。
- モデルの復元、JSONLのtag判別、メタ情報、排他と原子的保存、追記の前提を説明。
- docstringを除いた構文木が変更前と一致することを確認。実行処理の変更なし。
- docstring開始直後の半角空白を維持。
- pytest: 43件成功。Pyright: 0 errors / 0 warnings。
- 誤入力用typecheck/negative.pyでは想定するreportArgumentTypeを3件検出。
- コメントの目的・粒度の方針もAGENTS.mdへ反映。

## docstringと処理中コメントの配置整理

- メソッドのdocstringを目的・入出力・重要な前提へ絞った。
- 処理の順序と判断理由は該当コードの近くへ移し、同じ説明の重複を減らした。
- ロック範囲、モデルの検証・生成、型名の対応、メタ行の再生成、末尾の検査などを処理中に説明。
- 構文木の比較で、5個の実装ファイルの実行処理が変わっていないことを確認。
- pytest: 43件成功。Pyright: 0 errors / 0 warnings。
- 誤入力用typecheck/negative.pyでは想定するreportArgumentTypeを3件検出。
- 同じ配置方針をAGENTS.mdへ記録。

## 他形式への展開（2026-10-31 / v0.2.0）

- 環境: Python 3.12.14; pydantic 2.14.2; portalocker 3.2.0; ruamel.yaml 0.18.17; numpy 2.5.4; pytest 9.2.0; pyright 1.1.414
- pytest: 112 件成功。
- Pyright: 0 errors / 0 warnings。誤入力用の型検査も想定する3件を検出。
- docstringの半角空白、None戻り値注釈の省略、実装の非公開属性を構文木で点検。
- JSON / YAML / 独自テキストv1: モデル、入れ子、date、dict値の往復。
- YAML: テンプレートと既存文書のコメント・引用符・キー順・未知キーの保持、同時マージ、保存失敗。
- CSV: 階層列、可変キーの列集合、空一覧、空欄、見出しなし、BOM、alias、列衝突・欠損・重複の拒否。
- 独自テキストv1: None・bool・空文字・数値文字列・配列・空dictを保持。旧v0、重複、階層衝突、NaNを拒否。
- 波形: endian / signed / mask、配列形状、先頭サンプルの限定読取、境界の外部注入、復号ストリームの所有権、長さ不整合。
- example.py: 全形式の実行例に成功。波形の例は社内仕様と無関係な合成形式。

波形の実ヘッダーと実暗号方式は、社内側のheader_reader / decryptorを接続して別途確認する。
YAMLの配列は全体置換であり、要素単位のコメント対応付けは行わない。
独自テキストは未運用という前提でv1へ変更し、v0の自動互換は実装していない。
Pydanticの最低版2.7と、Windows以外のOSでの実行検証は未実施。
Excel保存との結合、修復API、メタ情報の取得APIは未実装。
