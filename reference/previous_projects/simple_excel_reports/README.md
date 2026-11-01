# openpyxl + Pydantic 帳票出力（小規模チーム向け）

## 1. 何ができるか

このサンプルは、2～3名で保守することを想定した**小さな帳票出力実装**です。対象は Pydantic v2 / openpyxl / `.xlsx`。

- `Record(BaseModel)` が `items: list[Item]` を持つ。**Recordは1行、Itemは指定された複数フィールドを右へ展開**。
- シートごとにItemのフィールド値からRecordを抽出。**同じItem内でAND/OR**、**複数Itemは1件でも一致すれば採用**、複数シート一致を許可。
- 比較：`==`, `!=`, `<`, `<=`, `>`, `>=`。値が`None`なら`!=`を含む全比較が不成立。
- 全シートで同じItemソート設定。**各RecordのItemだけ**を並べ替え、元データを変更しない。
- シートごとに異なるRecord/Item出力フィールドと位置別Item見出し名。
- 上部の共通項目はRecordから取得し、**そのシートの全Recordで同一か検証**。異なれば出力せずエラー。
- **コード生成方式**と**Excelテンプレート方式**。どちらも共通の`project()`を使用。
- データ0件でも各シートと1 Item分の空枠を残す。必要な見出し名が足りない場合はエラー。

> このコードは設計書 v2.3 を基にしています。`report_models.py`のRecord・Itemは業務に合わせて置き換える例です。`example.py`からの既存importも維持しています。

処理の構成と呼び出し順は、[Mermaid図付きの構成説明](docs/architecture.md)を参照してください。

## 2. フォルダー構成

```text
simple_excel_reports/
├─ reporting/
│  ├─ __init__.py
│  ├─ models.py       # BaseModelの定義：設定と出力値
│  ├─ project.py      # 条件判定・ソート・Excel非依存のデータ生成
│  ├─ template.py     # Excelテンプレート内の定義を読む
│  ├─ excel.py        # 2つのExcel描画方法
│  └─ api.py          # 外部向け窓口（ReportGenerator）
├─ report_models.py   # 利用側の業務モデル（Record / Item）
├─ report_patterns/
│  ├─ models.py       # コード方式・テンプレート方式のパターン型
│  ├─ registry.py     # 固定ID・表示名・用途・定義の取得先
│  ├─ inspection.py   # 点検帳票のReportSpec生成関数
│  └─ voltage.py      # 電圧確認一覧のReportSpec生成関数
├─ report_service.py  # GUI・CLIから呼ぶcreate_report
├─ templates/         # 提出用.xlsx（サンプル実行時に初回作成）
├─ docs/architecture.md  # Mermaid構成図・シーケンス図
├─ tests/             # データ変換・描画・ヘッダー・パターンのテスト
├─ example.py         # サンプル入力・テンプレート見本作成・実行例
└─ requirements.txt
```

専用のRepository、Serializer基底クラス、プラグイン機構、依存性注入コンテナは**導入していません**。今の規模では効果より複雑さが大きいためです。

## 3. 最初の実行

Python 3.11以上を想定します。

```bash
python -m pip install -r requirements.txt
python example.py
python -m pytest -q
```

実行すると、以下のテンプレートと完成帳票が作られます。

- `帳票_コード方式.xlsx`：Python設定に沿って新規作成
- `templates/inspection_submission.xlsx`：Excel側で編集できる提出用テンプレート
- `帳票_テンプレート方式.xlsx`：テンプレートを複製して値を入力した完成帳票
- `帳票_電圧確認一覧.xlsx`：電圧一覧だけの帳票

テンプレートは存在しない場合だけ作成し、編集済み内容を保持します。
完成帳票は同名ファイルを上書きします。以前のルート直下の`帳票テンプレート.xlsx`は使用しません。

テストには既存の帳票処理に加え、印刷ヘッダーの設定・保存後の再読み込み・入力検証を含めています。

## 4. 利用方法：コード生成方式

帳票の入口は`ReportGenerator`の2メソッドだけです。

```python
from reporting import ReportGenerator
from example import Record, Item, example_spec, sample_records

generator = ReportGenerator(Record, Item)
records = sample_records()

# 1) Pythonの設定に従って新規Excelを生成する
workbook = generator.code(records, example_spec())
workbook.save("out_code.xlsx")

# 2) Excelに書き込む前の値をテスト・検証したい場合
logical_data = generator.prepare(records, example_spec())
print(logical_data.sheets[0].rows)
```

`report_patterns/inspection.py`の`build_inspection_spec()`（`example_spec`の正本）に、シート条件（AND/OR）、上部項目、Record列、Item列、位置別見出しをまとめています。**フィールド名はすべてPydanticモデルの属性名**で指定してください。

## 5. 利用方法：テンプレート方式

```python
from reporting import ReportGenerator
from example import Record, Item, sample_records

generator = ReportGenerator(Record, Item)
workbook = generator.template(sample_records(), "templates/inspection_submission.xlsx")
workbook.save("out_template.xlsx")
```

### 5-1. 各帳票シートのセルに書く目印

| 入力文字 | 意味 | 置く場所 |
|---|---|---|
| `{{header:department}}` | Record由来の上部共通値 | 一覧より上の自由なセル |
| `{{record:record_id}}` | Recordのフィールド | **一覧の見本行**（横並び） |
| `{{item:temperature}}` | Itemのフィールド | **Recordと同じ見本行**（横並び） |
| `{{item_title}}` | 位置別のItem見出し | Item見本ブロックの**左上**、見本行より上 |

例：`A3`に「担当部署」、`B3`に`{{header:department}}`。`A7`に`{{record:record_id}}`、`B7`に`{{record:equipment}}`、`C7`に`{{item:temperature}}`、`D7`に`{{item:pressure}}`。`C5:D5`を結合し、`C5`に`{{item_title}}`。`C6,D6`に通常の列見出し文字列。5～7行目の**Item見本を列方向に複製**、7行目の**Record見本を行方向に複製**します。

テンプレート側では見出しの書式・罫線・列幅・結合・行高をExcelで自由に編集できます。ただし、複製範囲を跨ぐ結合セルや、展開先の既存データには対応しません。

### 5-2. 特別なシート `__report__` の記入方法

テンプレートには**設定用シートを1枚**追加します。完成帳票ではこのシートを自動的に取り除きます。

**全シート共通の設定**

| セル | 内容 | 例 |
|---|---|---|
| `A1` | 項目名（説明用） | `sort_field` |
| `B1` | Itemソートのフィールド | `order` |
| `A2` | 項目名（説明用） | `descending` |
| `B2` | 降順かどうか。Excelの真偽値 | `FALSE` |

**シートの振り分け条件：A4:E4を見出し、5行目から1条件1行**

| A sheet | B logic | C field | D operator | E value |
|---|---|---|---|---|
| 温度一覧 | AND | kind | == | A |
| 温度一覧 | AND | temperature | >= | 10 |
| 電圧一覧 | OR | kind | == | B |
| 電圧一覧 | OR | voltage | >= | 100 |

- **同一シートではすべて同じAND/OR**を指定してください。AND条件は同一のItemで評価します。
- `E`列はExcelのセル型が使用されます。数値は数値セル、日付は日付セルを使います。`"10"`という文字列は数値10と比較できません。
- フィルター条件は**複製したデータ全体に適用**します。Itemの一部だけを抜き出す方式ではありません。

**Itemの位置別見出し：G4:I4を見出し、5行目から1位置1行**

| G sheet | H position | I title |
|---|---:|---|
| 温度一覧 | 1 | 初期測定 |
| 温度一覧 | 2 | 中間測定 |
| 温度一覧 | 3 | 最終測定 |
| 電圧一覧 | 1 | 初回 |
| 電圧一覧 | 2 | 2回目 |
| 電圧一覧 | 3 | 3回目 |

出力対象Record内のItem最大件数が位置別見出し名の数を超えたらエラーにします。Itemが0件なら位置1の見出しだけを残します。

## 6. 仕様上の留意点

- **Excelテンプレートは「自由な任意書式を無制限に複製するエンジン」ではありません。** 最初の実装で対応するのは、`Item`の**連続した複数列のブロック**、`Record`の**単一見本行**、ブロック内部で完結する結合セルと基本書式です。
- **Item領域の右側、Record領域の下側は空けてください。** 既存の数式・固定セルを動かす機能はありません。展開先に値や結合があればエラーにします。
- テンプレートの実装は**式の参照先変更、グラフ・画像の複製、Excelテーブルの拡張**には対応しません。印刷範囲や印刷改ページの自動調整も未対応です。複雑な帳票には実Excelで動作確認が必要です。
- `Record.items=[]`はItem条件に一致しないので、**今回の抽出ルールではどのシートにも出ません**。ただし行データを構成する一般規則として、出力対象にしたRecordではItemが空欄になるよう実装しています。
- **並べ替えは安定ソート**です。値が同じItemは元順を維持し、`None`のItemは昇順・降順とも最後へ置きます。Record一覧の行順は入力どおりです。
- **条件値の`None`は指定不可**。Item側の`None`は比較不成立です。比較値の型不一致はエラーにします。
- 記載の位置別名称は**出力順の位置**に付く見出しです。`order`の意味を業務で保証するのは元データ側です。
- Excelファイル保存は呼び出し側が`workbook.save(path)`で行います。元テンプレートの上書きを避けるため、**出力パスは別に**してください。

## 7. 印刷用ヘッダーの動的設定

タイトル・共通項目・ページ番号を、印刷用ヘッダーの左／中央／右へ配置できます。
Excelの「ページレイアウト」または「印刷プレビュー」で確認してください。
ページ番号と総ページ数はExcelが印刷時に計算します。

### コード方式

```python
from reporting import PrintHeaderSpec

spec = example_spec()
sheet = spec.sheets[0]
sheet.show_table_headers = False  # セル上部の共通項目を表示しない
sheet.print_header = PrintHeaderSpec(
    title="設備点検結果一覧",  # シート名とは別に指定できる
    left="担当部署：{{header:department}}",
    center="{{title}}",
    right="（{{page}}/{{pages}}）",
    font="Meiryo",
    size=10,
)
workbook = generator.code(records, spec)
workbook.save("out_code.xlsx")
```

| マーカー | 表示する内容 |
|---|---|
| `{{title}}` | `PrintHeaderSpec.title` の文字列 |
| `{{header:department}}` | シート内で一致検証したRecordの `department` 値 |
| `{{page}}` | 現在ページ |
| `{{pages}}` | 総ページ数 |

`header:`の後ろには任意のRecordフィールド名を指定できます。セル用の
`headers` に含めていないフィールドも参照でき、一致検証の対象になります。
対象Recordが0件なら値は空文字です。通常の `&` はそのまま記入できます。
複数項目は改行 `\n` で並べられます。ページ番号を消す場合は `right=""` とします。
左・中央・右の内容はそれぞれ自由に変更できます。

`show_table_headers=True` ならセル上部にも共通項目を出せます。`False` の場合、
コード方式の表は1行目から始まります。指定しない場合は従来どおり `True` です。
`print_header=None`（既定）なら印刷ヘッダーの設定を行いません。

### テンプレート方式

`__report__` シートの **K4:P4** を以下の見出しにし、5行目から1シート1行で設定します。

| K sheet | L title | M left | N center | O right | P show_table_headers |
|---|---|---|---|---|---|
| 温度一覧 | 設備点検結果一覧 | 担当部署：{{header:department}} | {{title}} | （{{page}}/{{pages}}） | FALSE |

M～Oはコード方式と同じマーカーを使用します。空欄はその位置を非表示にします。
P列はExcelの真偽値 `TRUE` / `FALSE` を指定し、空欄なら `TRUE` です。
この設定行がないシートは、テンプレートに設定済みの印刷ヘッダーを保持します。
設定行がある場合、左・中央・右を上書きし、先頭・偶数ページも同じヘッダーを使用します。

P列が `FALSE` の場合はセルの `{{header:...}}` を空欄にします。
固定文字の「担当部署」や行の削除・移動は行わないため、テンプレート側で配置を調整してください。
テンプレートの設定行ではフォントはMeiryo、サイズは10を使用します。

`python example.py` は両方式とも印刷ヘッダーを使うサンプルを生成します。
従来のセル表示の例は `example_spec()` / `make_template(path)`、
印刷ヘッダーの例は `example_spec(print_headers=True)` /
`make_template(path, print_headers=True)` で取得できます。

## 8. 担当者ごとの変更箇所

| 変更したい内容 | 原則変更する場所 |
|---|---|
| Record/Itemのフィールド追加 | `report_models.py` |
| パターンの追加・画面の表示名変更 | `report_patterns/registry.py` |
| シート別の条件・列を変更 | コード方式：`ReportSpec`／テンプレート方式：`__report__` と各シートの目印 |
| 書式・罫線・結合を変えたい | コード方式：`excel.py`／テンプレート方式：`.xlsx` |
| 比較演算子や並べ替えの仕様変更 | `project.py` |
| 新しいテンプレート記法の追加 | `template.py` と対応する`excel.py`の処理 |

**現段階ではこれ以上の基底クラス・共通層を追加しない方針**です。実際に複数の帳票で重複が発生してから抽象化するほうが、保守人数に見合います。

## 9. GUIから使う帳票パターン

1パターンは複数シートを含められる1ブック全体です。登録一覧はPythonで管理し、
画面の表示名とプログラム用の固定IDを分けています。

| 固定ID | 表示名 | 方式 |
|---|---|---|
| `inspection_standard` | 点検結果一覧（標準） | コード |
| `inspection_submission` | 点検結果一覧（提出用） | テンプレート |
| `voltage_summary` | 電圧確認一覧 | コード |

```python
from example import sample_records
from report_patterns import get_pattern, list_patterns
from report_service import create_report

# GUIはこの一覧のname/descriptionを表示し、選択項目にidを関連付ける。
for pattern in list_patterns():
    print(pattern.id, pattern.name, pattern.description)

# GUIでは選択されたIDと、選択済みデータを渡す。
selected_id = "inspection_standard"
selected_records = sample_records()[:2]
workbook = create_report(get_pattern(selected_id), selected_records)
workbook.save("selected_report.xlsx")
```

`create_report`はPySide6に依存しません。データ取得・選択・保存先指定・例外の表示は
GUI側が担当し、データ検証とExcel生成は帳票側が担当します。GUI本体は未実装です。
`report_service.py`は今回の`report_models.Record/Item`を使う利用側の窓口です。

パターンを追加するには、コード方式なら新しいReportSpecを毎回作る関数を用意し、
`registry.py`へ`CodeReportPattern`を登録します。テンプレート方式なら.xlsxを配置し、
`TemplateReportPattern`へパスを登録します。テンプレート内の定義は登録一覧と二重管理しません。
登録一覧は読み取り専用で、定義関数は毎回新しい設定を返します。
