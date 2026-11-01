# 加工・解析・互換保存・帳票出力の使い方

全体の流れ・構成・クラス・ロック・版互換は[ARCHITECTURE_GUIDE.md](../previous_projects/data_manager_redesign/ARCHITECTURE_GUIDE.md)のMermaid図で確認できます。

2026-11-01 / v0.4.0。項目・計算は架空の接続例。

構成を変えた理由と原則の適用は[READABILITY_REVIEW.md](../previous_projects/data_manager_redesign/READABILITY_REVIEW.md)、
排他・後始末・外部反映の保証は[EDITING_AND_EXTERNAL_UPDATES.md](../previous_projects/data_manager_redesign/EDITING_AND_EXTERNAL_UPDATES.md)を参照。

一連の具体的な加工・解析・再解析の手順は[END_TO_END_GUIDE.md](../previous_projects/data_manager_redesign/END_TO_END_GUIDE.md)を参照。

## 使う側の入口

```python
from pathlib import Path
from examples.analysis_workflow import AnalysisService, process_data

analysis = AnalysisService(Path("analysis"))

# 加工用の値と、保存時に引き継ぐ旧項目を読み分ける。
processing, retained = analysis.load_processing(Path("source_v2.json").resolve(), raw_values)
presets = process_data(processing)
analysis.save_initial(presets, retained_values=retained)

# 編集用管理オブジェクトを経由せず、Presets自身を編集する。
with analysis.edit() as presets:
    presets.threshold = 110
    analysis.save_settings(presets, overwrite=True)
    # 測定行を変更したときだけ呼ぶ。
    # analysis.save_measurements(presets, overwrite=True)
    analysis.save_settings(presets, path="settings_v2.json", target_version=2)
```

設定はsettings.yaml、測定行はmeasurements.jsonlとして独立保存する。
初回保存は一式を揃え、失敗すれば今回の新規ファイルだけを削除する。
解析後は呼び出した保存対象だけを更新する。自動変更検出の仕組みは追加しない。

編集中の値はAnalysisPresets一つ。維持情報と編集権はサービス内部で管理する。
Settingsは入出力の境界で使い、Presetsと二つの編集可能な表現を常設しない。
通常保存は最新、旧版出力はtarget_versionを明示する。
既存ファイルは既定で拒否し、更新時だけoverwrite=Trueを渡す。

閲覧・帳票ではanalysis.load()からAnalysisPresetsを取得する。
この読取結果を後から保存する使い方はせず、更新時はedit()で改めて読み込む。
一般の外部エディタでの手修正はアプリの編集終了後に行い、再度開いて反映する。

## 誰が何を担当するか

```text
旧設定 → 辞書Repository → 隣接版upcast → 現在のSettings
                                           ↓ 必要項目を明示して取り出す
生データの値 ───────────────────────→ ProcessingPresets
                                           ↓ 加工
                                      AnalysisPresets
                                           ↓ 編集と対象別保存
                              設定YAML / 測定JSONLを独立保存
                                           ↓ 集計・帳票明細
                                      CSV / JSONL / Excel
```

- analysis_models.py：加工・解析に必要な項目。
- settings_versions.py：辞書の版変換、保持・廃止の規則、現在モデルによる検証。
- analysis_files.py：ファイルとの対応、保存、初回失敗の後始末。
- analysis_workflow.py：編集開始・終了、保存の権利確認、加工例。
- report_export.py：帳票明細と出力形式の選択。
- external_updates.py：保存済みの値の外部反映と再試行。
- run_analysis_workflow.py：これらを使う順序。

汎用Repositoryへ業務項目を入れず、継承で一つの巨大な管理クラスへまとめない。

## 隣接版キャスト

例はV2→V3。V2→V6も同じVersionConverterへ隣接版関数を追加してつなげられる。

```python
converter = VersionConverter(
    current_version=6,
    upcasts={2: upcast_2_to_3, 3: upcast_3_to_4, 4: upcast_4_to_5, 5: upcast_5_to_6},
    downcasts={6: downcast_6_to_5, 5: downcast_5_to_4, 4: downcast_4_to_3},
)
```

キーは変換元の版。共通処理が必要経路を事前確認し、版番号を更新する。
全版のBaseModelや工程ごとの版クラスは作らない。
版項目がない場合だけV0とし、不正値・bool・未来版をV0へ読み替えない。
INIの文字列版番号等は形式固有の読取側で正規化する。

例ではthreasholdをthresholdへ改名し、gainを1.0で補完する。
以前使用していたoperator_noteはretained_valuesへ保存して維持し、
保存されていただけのdraft_flagは最新・旧版出力の両方から廃止する。
retained_valuesはこの例の保存規則であり、全データへ強制する汎用の予約領域ではない。
空文字・None・0・Falseも存在する値として維持する。

downcastは旧版の出力項目を明示する。新項目の除外と、旧項目の不正値の許容は別。
必要な旧仕様の範囲・単位・必須条件をキャスト関数で検証する。
版変換後のYAML保存では既存文書をマージせず、廃止キーの復活を防ぐ。
そのため既存コメント・引用符・順序の保持は保証しない。

## 帳票を出す

```python
from examples.report_export import ReportExportService, build_report_rows
from examples.excel_reports_adapter import build_voltage_excel

rows = build_report_rows([analysis.load()])
reports = ReportExportService(Path("reports"), excel_writer=build_voltage_excel)
reports.export("summary.csv", rows)
reports.export("summary.jsonl", rows)
reports.export("summary.xlsx", rows)
```

明細を一度組み立て、CSV / JSONLはRowsRepository、Excelは既存帳票エンジンへ渡す。
帳票は加工・解析へ読み戻さない。例のExcelは電圧項目だけを表示し、CSV / JSONLの判定列は載せていない。

既存excel_reportsの登録パターンにはPrintHeaderSpec参照、旧report_modelsには基底契約不一致がある。
外部プロジェクトは変更せず、現行ReportGenerator / ReportRecord / ReportItemと接続例用ReportSpecを使う。
任意依存の遅延読込のため、この接続例ではcreate_modelで最小派生モデルを作る。
実アプリがExcelへ常時依存する構成なら、通常の派生クラス定義でよい。

## 外部情報を更新する

```python
updates = ExternalUpdateService(analysis, targets={
    "summary": create_summary_writer(Path("latest_status")),
})
with analysis.edit() as presets:
    presets.threshold = 110
    analysis.save_settings(presets, overwrite=True)
    result = updates.refresh(presets=presets)

# ボタン操作でも、保存済みデータから再実行する。
result = updates.refresh()
```

refreshは保存済みの値を読み直す。presets引数は編集権の確認に使い、その未保存値を送らない。
外部障害で解析データを巻き戻さない。失敗先だけの再実行もできる。
DBの一意キーと重複防止、画面通知、ログファイル設定は実アプリ側で接続する。

## 実行

プロジェクトルートで、まだ存在しない出力先を指定する。

```powershell
$env:PYTHONPATH = "src;."
.\.venv\Scripts\python.exe -m examples.run_analysis_workflow .\workflow_output
```

Excelも試す場合はexcel_reportsとその依存ライブラリをimport可能にする。

```powershell
$env:PYTHONPATH = "src;.;..\excel_reports"
.\.venv\Scripts\python.exe -m examples.run_analysis_workflow .\workflow_excel_output --excel
```

## 未実装の範囲

実業務のモデル・キャスト関数、DataFrame / ndarrayの永続化、行単位の維持情報対応付け、
ファイル間の業務整合検証、実DB・実画面、INI、非公開の波形ヘッダーは未移植。
強制終了時の保存残骸の復旧、既存データの複数ファイル同時更新、決定版の権限管理も追加していない。
