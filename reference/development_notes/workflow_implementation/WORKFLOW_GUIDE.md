# 加工・解析・互換保存・帳票出力をつなぐ具体例

2026-10-31 / v0.3.0。実際の業務項目を移植する前の、動作する接続例。

## この構成で解決すること

処理メソッドがSettingsの奥を自由に参照すると、何を必要とする処理かが見えなくなる。
用途別Presetsへ必要項目を明示し、ファイルとPresetsの対応をアプリ側servicesへ集める。
項目の再定義自体を悪とせず、対応付けが複数メソッドへ散らばらないことを優先する。

一方、古いキー名や版番号の分岐は処理メソッドへ渡さない。
辞書の隣接版upcast / downcastを先に適用し、現在の値として検証する。
過去版のBaseModelや加工V3Presetsのようなクラスは作らない。

```text
旧設定ファイル → ObjectRepository[dict] → 隣接版upcast → SettingsDocument
                                                           ↓ 明示的な取り出し
生データの値 ───────────────────────────────────→ ProcessingPresets
                                                           ↓ 加工例
                                                     AnalysisPresets
                                                           ↓
                                       設定と測定行を独立ファイルへ保存
                                                           ↓ 再読・編集
                                    変更した対象だけsave_settings / save_measurements
                                                           ↓
                                              帳票明細list[ReportRow]
                                                 ↓       ↓       ↓
                                                CSV    JSONL   Excel
```

今回の加工は値に識別子を付けるだけの架空例であり、実際の加工・解析ロジックを表すものではない。
DataFrame / ndarrayの保存規則や非公開の波形ヘッダーは推測して実装していない。

## 最初に見るファイルと、その役割

| ファイル | 意図と得られる効果 |
| --- | --- |
| `examples/analysis_workflow.py` | 用途別Presets、辞書のキャスト、ファイルとの対応、帳票明細の組立を具体化。業務項目の変更場所が見える |
| `examples/run_analysis_workflow.py` | 初回保存→再読→設定だけ更新→旧版出力→帳票出力を順に実行。使い方の入口 |
| `src/data_manager/versioning.py` | 隣接版キャストの実行順、経路不足、不正版を共通管理。利用側が繰返しループを書かずに済む |
| `examples/excel_reports_adapter.py` | 共通明細を既存ExcelのReportRecord / ReportItem契約へ変換。Excel依存を汎用Repositoryから分離 |
| `tests/test_versioning_workflow.py` | 元データを壊さない版変換、維持・廃止項目、手修正の再読、差分保存、上書き競合を実ファイルで確認 |

`Settings`は保存境界の現在値、`ProcessingPresets`と`AnalysisPresets`は処理に必要な現在値を明示する。
変換は`load_processing`、`load_analysis`、`save_settings`へ集約する。
Settingsの編集可能な別コピーをSessionに常設せず、編集値はAnalysisPresetsへ置く。
SettingsDocument / AnalysisSessionは処理値と維持情報をまとめるだけで、業務フィールドを再宣言しない。

## 版の橋渡しと保持・廃止

説明を短くするため、例はV2→V3とする。仕組みはV2→V3→V4→V5→V6にも同じように使える。

```python
converter = VersionConverter(
    current_version=6,
    upcasts={2: upcast_2_to_3, 3: upcast_3_to_4, 4: upcast_4_to_5, 5: upcast_5_to_6},
    downcasts={6: downcast_6_to_5, 5: downcast_5_to_4, 4: downcast_4_to_3},
)
```

キーは変換元の版。版番号の更新は共通処理が行う。
全版の関数を必須にせず、必要な経路に関数が足りなければ、変換を始める前にエラーにする。
版項目がない場合だけV0。不正値、bool、未来版をV0へ読み替えない。
INI等で版が文字列になる場合の整数化は、形式・データ種固有の読取処理で行う。

例の規則は次のとおり。

| 項目 | 扱い |
| --- | --- |
| V2の`threashold` | V3の`threshold`へ改名 |
| V3の`gain` | V2読取時は1.0で補完。V2出力時は除外 |
| 以前使用していた`operator_note` | 維持対象。V3の`retained_values`へ保存し、終了・再読後もV2へ戻せる |
| 保存されていただけの`draft_flag` | 廃止。最新版にも旧版出力にも元値を引き継がない |

`retained_values`は今回の架空例の保存規則であり、汎用ライブラリが全データへ強制する予約領域ではない。
利用側のdecode / encodeとcastが、維持対象を決める。空文字・None・0・Falseもキーが存在すれば維持する。
全旧文書を自動保存したり、未知項目を丸ごと現在モデルへ混ぜたりしない。

downcastはその版の出力項目を明示する。新項目を除外することと、旧項目の不正値を許すことは別。
必要ならcast内で旧仕様の範囲・単位・必須条件を検証し、表現できない値は理由付きで拒否する。

## 呼び出し方

### 1. 読み込んで初回保存する

```python
application = AnalysisApplicationService(Path("new_analysis"))
processing, retained = application.load_processing(Path("source_v2.json").resolve(), raw_values)
session = AnalysisSession(presets=process_data(processing), retained_values=retained)
application.save_initial(session)
```

設定は`settings.yaml`、測定行は`measurements.jsonl`へ分けて保存する。
初回は新しい保存先を使う。save_initialは二つの保存を順番に呼ぶ最小例であり、一式の原子的保存は保証しない。
二つ目で失敗したときは一部が残る。実アプリへ組み込む前に、未完了表示・再試行方法を決める。

### 2. 再読・編集し、変更対象だけを保存する

```python
session = application.load_analysis()
session.presets.threshold = 110
application.save_settings(session, overwrite=True)
```

この操作は測定ファイルを開いて書き直さない。
測定値を変更した場合は`save_measurements(session, overwrite=True)`を呼ぶ。
自動変更検出の仕組みは追加せず、保存対象が呼出箇所から分かる操作にしている。
両方を編集したなら両方を呼ぶ。複数ファイルの同時成功保証はない。

毎回ファイルから読むので、一部ファイルを外部で手修正してからload_analysisを呼べる。
現在の例は識別子・数値等の個別検証を行うが、実業務固有のファイル間整合検証は未実装。
外部エディタはsidecarロックに従うとは限らないため、編集とアプリ保存を同時に行う保証はない。

### 3. 旧版へ別名出力する

```python
application.save_settings(session, path="settings_v2.json", target_version=2)
```

指定がなければ現在版。旧版出力も既存の保存先は既定で拒否する。
Repository / ObjectFileService / RowsFileServiceも、更新時は`overwrite=True`が必要になった。
append_jsonlは追記操作なので、この全件保存の許可とは別。
これは誤上書き防止の操作規則であり、決定版の権限管理や改竄防止機構ではない。

版変換を使う保存ではYAMLの既存文書をマージしない。
廃止キーの復活を防ぐ代わりに、既存のコメント・引用符・順序の保存は保証しない。
通常のObjectRepositoryは従来のマージを使える。版変換後の文書編集保持は別途設計する。

### 4. 共通明細から帳票を出す

```python
rows = build_report_rows([application.load_analysis()])
exporter = ReportExportService(Path("reports"), excel_writer=build_voltage_excel)
exporter.export("summary.csv", rows)
exporter.export("summary.jsonl", rows)
exporter.export("summary.xlsx", rows)
```

CSV / JSONLはRowsRepositoryを使い、Excelは注入した関数を使う。
帳票は解析へ読み戻さない。CSV / JSONLの共通明細を、Excelの表配置へ無理に一般化しない。
接続例のExcelはReportRecord / ReportItemの最小派生モデルを作り、電圧項目へ値を渡す。CSV / JSONLにある判定列はこのExcel例には載せない。
複数結果をまとめる場合の識別子、集計・並べ替え、実際の帳票パターンと列の選択は、実モデルで具体化する。

## 実行する

プロジェクトのルートで、まだ存在しない出力先を指定する。

```powershell
$env:PYTHONPATH = "src;."
.\.venv\Scripts\python.exe -m examples.run_analysis_workflow .\workflow_output
```

Excelも試す場合は、既存excel_reportsをimportできる環境と、その依存ライブラリが必要。

```powershell
$env:PYTHONPATH = "src;.;..\excel_reports"
.\.venv\Scripts\python.exe -m examples.run_analysis_workflow .\workflow_excel_output --excel
```

外部プロジェクトの登録パターンは現時点でPrintHeaderSpecをimportしているが、reportingの公開APIには存在しない。
本例は登録パターンを読み込まず、現在のReportGenerator / ReportRecord / ReportItemと、この接続例用のReportSpecで動作を確認する。
また、旧report_models.Record / Itemは現在のエンジンが要求する基底クラスを継承していないため使わない。
外部依存を遅延読込するこの例ではcreate_modelで最小派生モデルを作るが、実アプリでExcelを常用するなら通常のクラス定義でよい。
既存Excelプロジェクト自体は変更していない。登録済み・テンプレート方式すべての接続を確認したわけではない。

## 今回まだ実装しないこと

- 実業務のキャスト関数・Presets・DataFrame / ndarrayの永続化対応。現例の項目は架空。
- 行ごとに維持対象がある場合の識別子による対応付け、実ファイル間の相互検証。
- 初回一式の完了管理、複数ファイルの一括ロールバック、外部編集の保存前検出。
- DB書込・集約フォルダへの進捗反映。保存後に外部反映が失敗した際の再試行・重複防止は検討メモのまま。
- 決定版の属性管理。現在は上書き拒否と明示許可だけ。
- INI Serializer、非公開の実波形ヘッダー、全既存帳票パターンへの対応。

これらを自動化する基盤を先に増やさず、一系統の実モデルへ適用した際に必要な規則を確定する。
