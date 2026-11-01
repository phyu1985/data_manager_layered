# Excel帳票とDataManagerの配置

2026-11-01。現在の実ファイル配置を整理したもの。配置換えやファイルの移動はしていない。

親フォルダーは`<project>`。
`data_manager_redesign`と`excel_reports`は、その直下にある別フォルダーである。
以下では環境用の`.venv`、`.git`、`__pycache__`、egg-info、排他用`.lock`等を省略する。

## 1. ソースコードと実行例の配置

```text
<project>\
│
├─ data_manager_redesign/                 Repository・Serializerの再設計側
│  ├─ pyproject.toml                     依存ライブラリ・pytest・Pyrightの設定
│  ├─ AGENTS.md                          コーディングルール
│  ├─ README.md                          説明資料と実行例の入口
│  ├─ example.py                         基本形式の入出力例
│  │
│  ├─ src/
│  │  └─ data_manager/                   汎用のPythonパッケージ
│  │     ├─ __init__.py                  利用側へ公開するAPI
│  │     ├─ py.typed                     型情報を公開するための印
│  │     ├─ repositories.py              ObjectRepository・RowsRepository
│  │     ├─ model_conversion.py          モデルの辞書化・復元
│  │     ├─ file_io.py                   ファイル／フォルダのロック・原子的保存
│  │     ├─ versioning.py                辞書の隣接版変換・版互換サービス
│  │     ├─ services.py                  固定パス用の任意の薄い窓口
│  │     ├─ waveform.py                  波形の読取・peek・外部関数の接続
│  │     ├─ errors.py                    共通の設定・形式エラー
│  │     └─ serializers/
│  │        ├─ __init__.py
│  │        ├─ json.py                   単一モデルのJSON
│  │        ├─ yaml.py                   YAMLと文書マージ
│  │        ├─ csv.py                    行データのCSV
│  │        ├─ jsonl.py                  行データのJSONL・型判別・メタ情報
│  │        ├─ custom_text.py            独自テキスト
│  │        └─ field_paths.py            階層フィールドの展開・復元
│  │
│  ├─ examples/                          アプリ固有の組立・業務モデルのサンプル
│  │  ├─ end_to_end.py                   生データから再解析・帳票までの実行入口
│  │  ├─ analysis_models.py              Settings・Measurement・用途別Presets
│  │  ├─ analysis_workflow.py            AnalysisService・編集の寿命・保存の許可
│  │  ├─ analysis_files.py               ファイル名・項目対応・初回保存の後始末
│  │  ├─ settings_versions.py            この例の設定のupcast／downcast
│  │  ├─ report_export.py               共通帳票明細・CSV／JSONL／Excelの振分
│  │  ├─ excel_reports_adapter.py        共通明細からExcel帳票エンジンへ接続
│  │  ├─ external_updates.py            外部再反映・集約JSONの更新例
│  │  ├─ run_analysis_workflow.py        外部反映・旧版出力も含む別の組立例
│  │  ├─ application_services.py         ファイル単位のサービスをまとめる基本例
│  │  └─ data/
│  │     └─ raw_readings.csv             end_to_endで読む生データの例
│  │
│  ├─ tests/
│  │  ├─ test_repositories.py
│  │  ├─ test_formats.py
│  │  ├─ test_waveform.py
│  │  ├─ test_services.py
│  │  ├─ test_review_regressions.py
│  │  ├─ test_versioning_workflow.py
│  │  ├─ test_edit_sessions.py
│  │  ├─ test_external_updates.py
│  │  ├─ test_excel_integration.py        別フォルダのExcelエンジンとの接続確認
│  │  └─ test_end_to_end.py              一連の処理・保存内容・ファイル数の確認
│  │
│  ├─ typecheck/
│  │  ├─ positive.py
│  │  ├─ negative.py
│  │  ├─ services_negative.py
│  │  ├─ versioning_positive.py
│  │  ├─ versioning_negative.py
│  │  ├─ analysis_positive.py
│  │  └─ analysis_negative.py
│  │
│  └─ end_to_end_example/                実行して生成したデータ。ソースではない
│     ├─ datasets/
│     │  └─ sample01/
│     │     ├─ settings.yaml             現在の解析条件
│     │     └─ measurements.jsonl        加工値と最新の確認順
│     └─ report.csv                     最後の状態から出した帳票
│
└─ excel_reports/                       既存のExcel帳票プロジェクト
   ├─ requirements.txt                  Excel側の依存ライブラリ
   ├─ README.md
   ├─ CHANGELOG.md
   ├─ example.py                        Excel単体で動かす実行例
   ├─ report_models.py                  Excel側の従来の業務モデル
   ├─ report_service.py                 登録帳票を生成する利用側の窓口
   │
   ├─ reporting/                        汎用Excel帳票エンジン
   │  ├─ __init__.py                    ReportGenerator等の公開API
   │  ├─ api.py                         ReportGeneratorの窓口
   │  ├─ contracts.py                   ReportRecord・ReportItemの共通契約
   │  ├─ models.py                      ReportSpec・SheetSpec・Column等
   │  ├─ project.py                     抽出・並べ替え・表示データの組立
   │  ├─ excel.py                       Excelの描画・配置
   │  └─ template.py                    テンプレート側の定義を読む
   │
   ├─ report_patterns/                  アプリで選択する帳票パターン
   │  ├─ __init__.py
   │  ├─ models.py                      コード方式／テンプレート方式の型
   │  ├─ registry.py                    パターンの登録・取得
   │  ├─ inspection.py                  点検帳票の定義
   │  └─ voltage.py                     電圧一覧の定義
   │
   ├─ templates/                        入力となる帳票テンプレート
   │  ├─ README.md
   │  └─ inspection_submission.xlsx
   │
   ├─ docs/
   │  ├─ DESIGN.md
   │  ├─ TEMPLATE_SPEC.md
   │  └─ architecture.md
   │
   └─ tests/
      ├─ test_report.py
      ├─ test_patterns.py
      ├─ test_contracts.py
      ├─ test_print_header.py
      └─ test_template_formula.py
```

`src/data_manager`が汎用部品で、`examples`がそれを使うアプリ側のサンプル。
加工・解析の業務コードを、すでに本番アプリのパッケージへ移植済みという配置ではない。
Excel側も、`reporting`が汎用エンジン、`report_patterns`等が利用側の定義という分担。

## 2. 二つのフォルダーをつないでいる場所

```text
data_manager_redesign/examples/end_to_end.py
  ↓ 最新の保存内容から帳票明細を作る
data_manager_redesign/examples/report_export.py
  ├─ CSV / JSONL → data_managerのRowsRepository
  └─ Excel → 注入したExcel生成関数
               ↓
data_manager_redesign/examples/excel_reports_adapter.py
  ↓ ReportRecord / ReportItemの契約に合わせる
excel_reports/reporting/api.py の ReportGenerator
  ↓ Workbookを生成
data_manager_redesign側で、指定された出力先へ保存
```

**接続例は`excel_reports/reporting`へ直接接続する。**
`excel_reports/report_service.py`や登録済み`report_patterns`を経由しているわけではない。
接続例用のReportSpecと最小の派生モデルを使っており、全登録帳票を統合した状態ではない。

Excel側のソースやテンプレートを、data_manager_redesignへコピーする構成にもしていない。
現在のサンプルは、Pythonの検索パスで二つのフォルダーを参照する。

```powershell
cd <project>\data_manager_redesign
$env:PYTHONPATH = "src;.;..\excel_reports"
.\.venv\Scripts\python.exe -m examples.end_to_end .\new_excel_output --report-format xlsx
```

Excel側の依存ライブラリも、実行するPython環境から利用できる必要がある。
出力先はまだ存在しないフォルダーを指定する。

## 3. テンプレートと生成物の違い

| 種類 | 現在の配置 | 扱い |
| --- | --- | --- |
| 生データの例 | data_manager_redesign/examples/data/raw_readings.csv | 入力。処理で上書きしない |
| 保存した解析データ | data_manager_redesign/end_to_end_example/datasets/sample01 | 初回保存後、編集で変更対象を更新 |
| 最新の帳票例 | data_manager_redesign/end_to_end_example/report.csv | 出力。解析へ読み戻さない |
| 登録パターン用テンプレート | excel_reports/templates/inspection_submission.xlsx | 帳票生成時の入力 |
| Excel単体例のテンプレート・帳票 | excel_reports直下の帳票テンプレート.xlsx、帳票_コード方式.xlsx、帳票_テンプレート方式.xlsx | Excel単体の例で使うもの。今回の解析保存先とは別 |

帳票の出力先は固定ではなく、実行時に指定したフォルダーで決まる。
`report.xlsx`を選ぶ場合は`report.csv`に加えて両方作るのではなく、指定形式の一つを生成する。

以前の動作確認で生成した次のフォルダーも、data_manager_redesign直下に存在する。
現在の標準例として見るのはend_to_end_exampleでよい。

```text
data_manager_redesign/
  example_output/
  service_example_output/
  workflow_example_output/
  workflow_editing_output/
  workflow_readable_output/
```

## 4. 説明資料の配置

現在の主な説明資料はdata_manager_redesign直下にある。

| ファイル | 読む目的 |
| --- | --- |
| FILE_LAYOUT.md | この配置図 |
| ARCHITECTURE_GUIDE.md | 全体フロー・クラス図・編集ロック・版互換 |
| END_TO_END_GUIDE.md | 生データから再解析・帳票までの使い方 |
| WORKFLOW_GUIDE.md | 各モジュールを組み合わせる基本手順 |
| READABILITY_REVIEW.md | 責務分離と命名を見直した理由 |
| EDITING_AND_EXTERNAL_UPDATES.md | 編集ロック・初回後始末・外部再反映 |
| FORMATS.md | 各ファイル形式の使い方と制約 |
| VALIDATION.md | 最新と過去の検証結果 |

同じ場所にあるDESIGN.md、API_PROPOSAL.md、MODEL_BOUNDARIES.md、VERSIONING_DESIGN.md、
SERVICES.md、REVIEW_REPORT.md、IMPLEMENTATION_REVIEW.md、APPLICATION_WORKFLOW_NOTES.mdは、
設計案・変更経緯・未解決事項の記録も含む。現在の呼び出し方は上の現行ガイドから確認する。
Excel側の追加ガイド`帳票出力_設計実装ガイド_v2.3.md`はexcel_reports直下にある。
