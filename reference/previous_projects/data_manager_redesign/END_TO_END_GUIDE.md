# 生データから再解析・帳票までの使い方

全体の流れ・構成・クラス・ロック・版互換は[ARCHITECTURE_GUIDE.md](ARCHITECTURE_GUIDE.md)のMermaid図で確認できます。

2026-11-01。最初に読むコードは`examples/end_to_end.py`の`run()`。

この例は、既存モジュールをアプリからどの順に呼ぶかを確認するためのもの。
画面は作らず、「画面で条件を入力した」「一覧から解析データを選んだ」に相当する箇所を関数で示している。
計算自体は架空で、実業務の解析結果を保証するものではない。

## まず動かす

プロジェクトルートで、まだ存在しない出力フォルダを指定する。

```powershell
$env:PYTHONPATH = "src;."
.\.venv\Scripts\python.exe -m examples.end_to_end .\end_to_end_output
```

生データは同梱の`examples/data/raw_readings.csv`を読む。値は10、18、22、30の四つ。
入力の内容は変更せず、入力ファイルのコピーも作らない。

通常生成するデータファイルは次の三つだけ。

```text
end_to_end_output/
  datasets/
    sample01/
      settings.yaml          条件。再解析で変更したら同じファイルを更新
      measurements.jsonl     加工値と、最新の確認優先順位
  report.csv                 最後の状態から作った帳票
```

排他制御の`.lock`ファイルは別途作られる。これは結果の世代コピーではなく、ロック用の補助ファイル。
初回解析用、再解析用という別名のデータファイルは作らない。
DBや集約情報のファイルも、この例では生成しない。

## この例の計算と、結果の見方

加工では先頭値10を基準にし、`(生の値 - 先頭値) × gain`を計算する。
gainの既定値は1なので、加工値は0、8、12、20となる。

解析では、しきい値に近い測定から確認できるように行を並べ替え、超過件数・平均・最大値を集計する。
同じ距離の行はIDで順序を確定する。
解析によって加工値を再補正しないため、繰り返し解析しても値は累積しない。

| 段階 | しきい値 | 確認する値の順 | 超過件数 |
| --- | --- | --- | --- |
| 加工後 | 10 | 0、8、12、20 | 解析前 |
| 初回解析 | 10 | 8、12、0、20 | 2 |
| 再解析 | 18 | 20、12、8、0 | 1 |

IDは入力順に0、1、2、3。平均は10、最大は20で、再解析しても変わらない。
超過の条件は`value > threshold`で、同値は超過に含めない。

この例で保存する解析結果は「最新の確認順」と「判定条件」。測定値は加工済みの数値を保つ。
個々の超過判定は、帳票を作るときに保存済みの条件から再計算する。
平均等の集計は画面表示用の`ReviewSummary`として返し、追加の集計ファイルは作らない。
判定値自体を永続化したい実業務では、その項目を保存モデルへ明示して追加する。

## 各段階で使うもの

| 段階 | アプリ側で呼ぶもの | 内側で使う既存モジュール |
| --- | --- | --- |
| 生データ読取 | `read_raw(path)` | `RowsRepository[RawReading]`、CSVまたは外部JSONLのSerializer |
| 加工条件を集める | `ProcessingPresets(...)` | 用途別BaseModel。ここではファイル操作なし |
| 加工 | `process_readings(processing)` | 既存`process_data()`で測定モデルを作り、この例の補正を適用 |
| 初回一式保存 | `analysis.save_initial(processed)` | `AnalysisService`→`AnalysisFiles`→設定・測定のRepository |
| 解析データ一覧 | `list_analyses(parent)` | `AnalysisService.exists()`。ファイル名の知識は`AnalysisFiles`内 |
| 解析対象選択 | `select_analysis(candidates, name)` | 選んだフォルダを確定。モデル読取はまだしない |
| 解析開始・読取 | `with analysis.edit() as presets:` | フォルダロック→設定の版変換→設定と測定のモデル復元 |
| 解析 | `analyze_readings(presets)` | 処理値だけを使う計算。Repositoryを呼ばない |
| 解析保存 | `analysis.save_measurements(presets, overwrite=True)` | 測定JSONLだけを更新 |
| 再解析 | 新しい`with analysis.edit()`で再読し、条件変更・解析 | 初回解析と同じ処理を再利用 |
| 再解析保存 | `save_settings`と`save_measurements` | 今回は条件と順序の両方を変えたため、二ファイルを更新 |
| 帳票 | `build_report_rows([analysis.load()])`→`reports.export(...)` | 共通明細→CSV / JSONLのRepository、またはExcelアダプター |

## 呼び出しの中心部分

### 生データを読み、加工用Presetsを作る

```python
raw = read_raw(raw_path)
processing = ProcessingPresets(
    raw_values=[row.value for row in raw],
    gain=1,
    threshold=10,
)
processed = process_readings(processing)
analysis.save_initial(processed)
```

この例は、gainとthresholdを画面で指定した想定。
既存設定ファイルから取り出す場合は、既存の`analysis.load_processing(settings_path, raw_values)`を使える。
旧項目の維持情報も返るので、その場合は`save_initial(..., retained_values=retained)`で引き継ぐ。

加工前に、空データ・非有限値・不正な倍率等を検証する。
不正な入力なら出力フォルダを作り始めない。
この例の既知の項目に対する検証であり、汎用Repositoryの全モデル再検証を実装したものではない。

### 保存済み解析データを一覧から選ぶ

```python
candidates = list_analyses(data_directory)
selected = select_analysis(candidates, "sample01")
analysis = AnalysisService(selected)
```

実行例ではファイル数を抑えるため一つだけ作るが、一覧関数は複数の保存フォルダにも対応する。
実画面では候補の名前を一覧表示し、選択された名前を`select_analysis`へ渡す。
必要なファイルのないフォルダは候補から除外する。
一覧にあることは内容の正常性や未使用を意味せず、開くときにロック取得とモデル検証を行う。

### 初回解析を実行して保存する

```python
with analysis.edit() as presets:
    first = analyze_readings(presets)
    analysis.save_measurements(presets, overwrite=True)
```

加工直後のメモリ上の値を流用せず、選んだフォルダの保存内容を読み直す。
この解析は測定行の順序だけを変えるので、設定YAMLは書き直さない。
`overwrite=True`は、今回編集中の解析データを更新する明示指定。
元の生データや、別の決定版を更新する指定ではない。

### 再解析し、変更した内容を保存する

```python
with analysis.edit() as presets:
    presets.threshold = 18
    second = analyze_readings(presets)
    analysis.save_settings(presets, overwrite=True)
    analysis.save_measurements(presets, overwrite=True)
```

一度編集を終了してから改めて開くので、前回の保存結果を入力にする。
しきい値と確認順の両方が変わるため、今回は両方のファイルを更新する。
Presets自身の項目を操作し、Editor等の管理用オブジェクトをたどる必要はない。

初回保存失敗時の新規ファイル削除は既存サービスが担当する。
既存二ファイルの更新全体は一つのトランザクションではなく、途中のI/O障害で片方だけ更新される可能性は残る。

### 最後に一形式だけ帳票を作る

```python
rows = build_report_rows([analysis.load()])
reports.export("report.csv", rows)
```

帳票明細を作る前に再度読み、最新の保存内容を反映する。
CSVとJSONLは同じ`ReportRow`の一覧を使う。Excelは既存の`build_voltage_excel`へ委譲する。
帳票は閲覧・報告専用で、加工・解析へ読み戻さない。

## 変えて試す

```powershell
# 別の生データを使い、再解析の条件を変える
.\.venv\Scripts\python.exe -m examples.end_to_end .\another_output --raw .\my_raw.csv --second-threshold 15

# JSONL帳票だけを作る
.\.venv\Scripts\python.exe -m examples.end_to_end .\jsonl_output --report-format jsonl

# Excel帳票だけを作る。既存Excelプロジェクトと依存ライブラリが必要
$env:PYTHONPATH = "src;.;..\excel_reports"
.\.venv\Scripts\python.exe -m examples.end_to_end .\excel_output --report-format xlsx
```

生データは`value`列のCSVか、`{"value": 10}`等のメタなしJSONL。
外部JSONLは入力専用の設定で読み、解析データは別の内部用Repositoryがメタ付きで保存する。
出力先が既に存在する場合は拒否するので、別名を指定する。

Excel例は現在のエンジンへつなぐ電圧一覧で、既存の全登録パターンや実業務帳票を接続したものではない。
YAMLの元コメント保持、一般化した保存時再検証、実DB・画面等の未実装事項は、この利用例で完成した扱いにはしていない。
