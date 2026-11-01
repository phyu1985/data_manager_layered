# 検証結果

## 最新の確認（2026-10-31 / v0.3.0）

- 通常環境 + 既存excel_reports接続: pytest 195件成功。
- 最小依存版の別環境: 194件成功、任意の外部Excel接続テスト1件をスキップ。
- 通常環境のExcel検証には、同梱Python環境のopenpyxl等を追加の検索先として使用。専用venvへ依存をインストールせず、既存excel_reportsも変更していない。
- Pyright strict: src、従来のpositive、版変換positive、アプリ側の旧・新接続例で0 errors / 0 warnings。
- negative.py / services_negative.py / versioning_negative.py: 期待どおりreportArgumentTypeを3件 / 3件 / 2件検出。
- V2→V6の連鎖と逆変換、入力辞書の非破壊、変換経路不足の事前検出、不正・未来版の拒否、例外原因の保持を確認。
- JSON / YAML / 独自テキストで最新版を保存し、サービス再生成・元ファイル削除後に旧版出力して、維持項目だけが戻ることを確認。空文字・None・0・Falseも確認。
- 設定だけの更新で測定ファイルの内容と更新時刻が変わらないこと、手修正後の再読、新規保存競合で一件だけ成功することを確認。
- Excelは現行ReportGenerator / ReportRecord / ReportItemへ接続し、生成Workbookのシート名と識別子・数値を検査。
- run_analysis_workflowを実行し、最新設定、独立JSONL測定行、V2互換出力、CSV / JSONL / Excel帳票まで生成。
- 既存Excelの登録パターンはPrintHeaderSpec参照、旧report_modelsは基底契約不一致があるため未接続。接続例専用のReportSpecと最小派生モデルを使用。

今回の構成・呼出方法・未実装範囲はWORKFLOW_GUIDE.mdを参照。
実業務モデル・実キャスト関数・ファイル間整合・初回一式の完了管理・DB/進捗反映は、この架空例の検証には含まない。


## 前回の確認（2026-10-31 / v0.2.1）

- 通常環境: Python 3.12.14; pydantic 2.14.2; portalocker 3.2.0; ruamel.yaml 0.18.17; numpy 2.5.4; pytest 9.2.0; pyright 1.1.414
- 通常環境のpytest: 168 件成功。
- 最低バージョン環境のpytest: 168件成功。Python 3.12.14、Pydantic 2.7.0、portalocker 2.8.0、ruamel.yaml 0.18.0、NumPy 1.26.0。
- 最低バージョンの確認は別の仮想環境で行い、通常の専用環境は変更していない。
- Pyright: 0 errors / 0 warnings。Repository・Service・アプリ側の組み立て例を対象にした。
- 誤入力用negative.pyとservices_negative.pyは、それぞれ想定するreportArgumentTypeを3件検出。
- 24個のPythonファイルで、docstringの空白、None戻り値注釈の省略、実装の非公開属性を構文木で点検。
- example.pyとexamples/application_services.pyは実行成功。
- JSONの重複キー・数値のオーバーフロー、dictの暗黙キー変換、YAML循環エイリアス・編集用スカラー、再帰CSV列推定、待機時間、外部ヘッダー返却値に回帰テストを追加。
- 小さなサービス窓口から、設定・測定CSV・混在JSONL・波形を既存の型・例外とともに扱えることを確認。

実波形の社内header_reader / decryptorとの結合、Windows以外のOS、Pylance画面での表示、追記中のプロセス強制終了は未確認。
設計判断を要する提案はREVIEW_REPORT.md、サービスの使い方はSERVICES.mdを参照。

## 過去の検証記録

以下は各段階の記録です。現在の対応状況は上の最新項目を参照してください。
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

