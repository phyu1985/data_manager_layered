# CSV設定：項目を宣言して読む

## 主に使う指定

通常のヘッダは、CsvHeaderOptions.fieldsへ項目を記載順に並べます。項目数が読取件数になるため、別のrow_countを合わせる必要はありません。

```python
serializer = CsvSerializer(
    options=CsvOptions(delimiter=";", column_prefix="#"),
    metadata=CsvHeaderOptions(fields=(
        CsvHeaderField.whitespace("version"),
        CsvHeaderField.separated("count"),
    )),
)
```

```text
version   0
count:  1
#id;name;value
1;taro;3
2;jiro;4
```

型は4種類です。境界を表すクラスや、設定のための継承階層は追加していません。

| 設定 | 目的 |
|---|---|
| CsvOptions | 本文の列・区切り・空値 |
| CsvHeaderOptions | 項目が分かっているヘッダ。a〜g、AA・AAAの主役 |
| CsvHeaderField | 一項目の名前と書式 |
| CsvKeyValueHeaderOptions | 項目名が不定のkey-valueメタ。件数指定が基本 |

## ヘッダの一項目

| 作り方 | ファイルの例 |
|---|---|
| CsvHeaderField.value_only("version") | 0 |
| CsvHeaderField.compact("version") | version0 |
| CsvHeaderField.whitespace("version") | version   0 |
| CsvHeaderField.separated("count") | count:  1 |
| CsvHeaderField.separated("count", "=") | count = 1 |

項目名・区切りは各項目の生成時、重複は項目一覧の生成時に確認します。読取中に同じ設定を再検証しません。細かな既存書式にはCsvHeaderField(name, separator=...)も使用できますが、新しい例は意図が読める名前付きの生成方法へ統一しています。

## CsvHeaderOptionsの項目

| 項目 | 既定値 | 意味 |
|---|---|---|
| fields | 必須 | 読む順番の項目一覧。空一覧・重複名はエラー |
| comment_prefixes | () | 最初のメタより前の説明行を飛ばす記号 |
| allow_padding | False | メタ行の末尾の空CSVセルを許容。非空の余分な値はエラー |
| empty_as_none | True | メタの空値をNoneへ変換 |

説明コメントを飛ばすのは先頭だけです。後ろの#付き列名をコメントとして捨てません。fieldsを読んだら、残りはテーブルへ渡します。メタと本文の間に空行がなくても構いません。

固定ヘッダはCSVレコードとして扱い、delimiterを含む値や改行はCSVの引用規則で保ちます。名前付き値の有意な前後空白などは内側のJSON文字列として保存します。値だけの項目はCSVセルの値をそのまま保持します。説明コメントと元のスペース数は保存しません。

## CsvOptions：本文の9項目

| 項目 | 既定値 | 意味 |
|---|---|---|
| delimiter | "," | セル区切り1文字。セミコロン・タブ・半角空白も使用可能 |
| header | True | 列名行を消費・生成する。列名なし入力はFalse |
| columns | None | 指定するとファイルの見出しを全面置換し、出力列順も固定 |
| column_prefix | "" | #などの列名行の開始記号。header=Trueでのみ使用 |
| strip_column_names | False | ファイルから採用する列名だけの前後空白を除く |
| field_separator | "." | position.xのような入れ子のキーの区切り |
| empty_as_none | True | 本文の空セルをNoneへ変換 |
| by_alias | False | モデルの出力時にserialization_aliasを使用 |
| allow_trailing_empty_columns | False | 期待列数を超える末尾空セルだけを読取時に許容 |

columnsを指定した場合、元の列名行は消費しますが、名前や個数は採用しません。指定した名前と本文の列数を照合します。gの名前のない後半3列も、6個の名前を与えれば保持できます。余剰の非空値や列不足はエラーで、黙って切り捨てません。BaseModelで復元するなら、対象モデルにも必要な項目を定義します。

半角空白区切りは連続スペースをまとめて区切りとします。空セルは引用した空文字で表してください。strip_column_namesは本文の値を変更しません。

読み書きが違うときだけread_options / write_optionsを指定します。その方向の設定全体を置き換え、項目ごとの暗黙マージはしません。

```python
common = CsvOptions(delimiter=";", columns=("id", "name", "value"))
serializer = CsvSerializer(options=common, read_options=replace(common, header=False))
```

replaceはdataclassesからimportします。入力は列名なし、出力は列名付きになります。ヘッダの項目自体が版ごとに異なる場合は、別のSerializerを構成します。

## 項目名が不定の場合：件数指定を基本にする

```python
metadata = CsvKeyValueHeaderOptions.fixed_rows(2)
metadata = CsvKeyValueHeaderOptions.fixed_rows(2, separator=":")
```

separator省略時は本文と同じdelimiterのCSV2セル、指定時はテキストkey/valueです。件数が非負整数かはfixed_rowsで確認します。

テキスト特有の設定はas_textでまとめます。元の不変設定を変更せず、新しい設定を返します。

```python
metadata = CsvKeyValueHeaderOptions.fixed_rows(2).as_text(
    separator=":", multiple=True, prefix="# ",
)
```

| 指定 | 適用範囲 |
|---|---|
| separator | テキストのキー・値の区切り。半角空白または空白を含まない記号 |
| multiple | 一行に複数組を許容。値の空白はJSON文字列として引用 |
| prefix | 各メタ行の接頭辞 |
| empty_as_none | fixed_rowsなどの生成時に指定。メタの空値をNoneへ変える |

CSV形式の件数はCSVレコード数、テキスト形式は物理行数です。保存は一対一行なので、保存項目数を指定件数と一致させます。重複キー、不正な値、件数不足はエラーです。

空行・マーカーは例外的な入力向けに残しています。

```python
CsvKeyValueHeaderOptions.until_blank_line()
CsvKeyValueHeaderOptions.until_marker("[data]")
CsvKeyValueHeaderOptions.until_marker("[data]").as_text(multiple=True)
```

marker / row_count / boundaryを一つのコンストラクタへ渡して組み合わせる方法は廃止しました。生成メソッドがその方式の必要値だけを受け付けます。CsvKeyValueHeaderOptionsの直接生成はできません。

## a〜gと実行例

```powershell
python -m examples.csv_layouts outputs/layouts
python -m examples.csv_layouts outputs/g --pattern g
python -m examples.versioned_csv outputs/versioned-csv
```

| 例 | 設定上の違い |
|---|---|
| a | versionはcompact、countはseparated。列名の#と余分な空白を除く |
| b | versionはwhitespace、countはseparated。セミコロン |
| c | 先頭コメントを飛ばす。列名に#はない |
| d | 先頭コメントと列名の#を別々に扱う |
| e | header=False、3個のcolumns |
| f | versionはvalue_only、header=False、3個のcolumns |
| g | メタのallow_padding、6個のcolumnsによる全面置換 |

gのextra_1〜extra_3は未提示の意味を仮の名前で表しています。実際のモデルに合わせて指定してください。a〜gのcountは本文件数と一致しないため、自動的な件数照合はしません。

versioned_csv.pyはb.csvを元に、旧版CSVをupcastして現在モデルで編集し、現在版CSV / JSONL・旧版CSVへ保存します。メタはcount→group_count、本文はname/value→label/readingを同時に変えます。先頭version 0の解釈と、復元するモデルの検証を混同しません。

## 今回のAPI変更

| 直前の指定 | 新しい指定 |
|---|---|
| CsvFixedHeaderOptions(fields=...) | CsvHeaderOptions(fields=...) |
| CsvHeaderOptions(boundary="fixed_rows", row_count=2) | CsvKeyValueHeaderOptions.fixed_rows(2) |
| CsvHeaderOptions(boundary="blank_line") | CsvKeyValueHeaderOptions.until_blank_line() |
| CsvHeaderOptions(boundary="marker", marker="x") | CsvKeyValueHeaderOptions.until_marker("x") |
| metadata_separatorなど、テキスト固有の値 | 件数などの選択後、as_textでまとめて指定 |

上記は直前の版からの移行です。さらに古いCSVDumpOptions / CSVLoadOptions / CSVMetadataOptions、dump_options / load_options / metadata_optionsも既に廃止済みです。本文はoptions / read_options / write_options、ヘッダはmetadataへ渡します。

設定の確認は生成時、列数・件数・データ型・保存保護は実際の読書き時という責務で分けています。整理範囲と残した検証の理由は[検証と処理の整理](VALIDATION_FLOW.md)、二段形式は[AA・AAA](TWO_TABLE_CSV.md)を参照してください。
