# CSV・JSONL・YAMLのメタ情報を同じ入口で扱う

ファイル全体の項目と、テーブル本文は別の値として扱います。いずれの形式も`load_document()`で`RowsDocument(metadata=..., rows=...)`を受け取り、`save_document()`で一体として保存します。Repositoryを直接使う場合のAPIです。利用側のFileServiceではRowsDocumentRepositoryへメタの型を構成し、他のファイルと同じload/save/save_asで扱えます。

```python
from pathlib import Path
from DataManager import (
    CsvKeyValueHeaderOptions, CsvSerializer, JsonlSerializer, FileService, RowsDocumentRepository,
    RowsDocument, RowsRepository,
)
from examples.metadata import FileMetadata, Measurement

repository = RowsRepository(
    model=Measurement,
    base_directory=Path("data"),
    serializers_by_extension={
        ".csv": CsvSerializer(metadata=CsvKeyValueHeaderOptions.until_blank_line()),
        ".jsonl": JsonlSerializer(),
    },
)

document = RowsDocument(
    metadata=FileMetadata(version=4, device="A001"),
    rows=[Measurement(time=0, value=1.2)],
)
file = FileService(
    repository=RowsDocumentRepository(repository=repository, metadata_model=FileMetadata),
    path="measurement.csv",
)
file.save(document)
file.save_as("measurement.jsonl", document)

document = file.load()
document.metadata.version  # int
document.rows             # list[Measurement]
```

metaの業務項目をRepositoryは知りません。`metadata_model`を省略すると辞書、指定するとPydanticによる検証・生成を行ったモデルを返します。戻り値の型も指定に合わせて推論され、呼出側のcastは不要です。

## CSVの境界規則

同じ拡張子でも読取規則が違うため、内容から推測せずファイル用途ごとにSerializerを設定します。

| 規則 | 設定 | 境界の扱い |
|---|---|---|
| 空行 | `CsvKeyValueHeaderOptions.until_blank_line()` | 空のCSVレコード1件を境界にする |
| マーカー | `CsvKeyValueHeaderOptions.until_marker("[data]")` | 指定文字列だけの1セルのレコードを境界にする |
| 固定件数 | `CsvKeyValueHeaderOptions.fixed_rows(2)` | 先頭2レコードがメタ。境界用レコードはない |

空行の例です。

```csv
version,4
device,A001

time,value
0,1.2
```

マーカーの場合は空行の代わりに`[data]`、固定件数の場合は境界なしで`time,value`が続きます。固定件数の書込ではメタの件数が一致しなければエラーにします。足りない値の補完や余分な値の切捨てはしません。

「行」はCSVの論理レコードです。引用符内の改行は値の一部であり、空行や追加のメタとして数えません。`[data],something`は2セルなのでマーカーではありません。引用符付きの空文字1セルや、空白文字のある行も空レコードとは区別します。改行文字の数で固定バイト位置を求める形式は対象外です。

メタは重複のない非空キーと単一値の2列です。辞書・配列の暗黙の文字列化はせずエラーにします。書込順序は辞書・モデルの出力順です。CSVでは値は文字列として記録され、辞書での読込は`"001"`もそのまま保持します。型の復元には`metadata_model`を使います。空の値は既定でNone、保持するなら`CsvKeyValueHeaderOptions.until_blank_line(empty_as_none=False)`にします。本文の空欄や見出しは別のCsvOptionsで指定します。値だけのヘッダ・列名置換は[拡張形式ガイド](EXTENSION_GUIDE.md)を参照してください。

モデルの別名でメタキーを保存する場合は`save_document(..., metadata_by_alias=True)`を指定します。読取時のalias受入方針はモデルに従い、Serializer側で補正しません。

## JSONLでの保存

従来の型照合情報と業務の値は混ぜません。先頭行は次の形です。

```json
{"__meta__":{"schema_version":2,"mode":"single","models":["Measurement"]},"metadata":{"version":4,"device":"A001"}}
```

後続行は従来どおり本文です。混在モデルのtypeキーや固定タグの設定も使えます。`metadata.version`は業務データの版であり、`__meta__.schema_version`はJSONLの文法の版です。

従来のメタ行だけを持つ形式版1も読み込めます。その利用者メタは空辞書です。通常の`save()`は従来の形式版1、新しい`save_document()`は利用者メタを含む形式版2を生成します。この拡張前の読み込みコードは形式版2を読めません。追記は先頭メタ行を検証して保持し、本文だけを追加します。メタを変えるときは文書全体を保存してください。

メタなし外部JSONLを`JSONLLoadOptions(metadata="absent")`で読む場合、`document.metadata`は空辞書です。この設定での`save_document()`は、読取設定と矛盾するためエラーにします。

## 通常の一覧APIとの使い分け

- `RowsRepository.load()`は本文だけを返します。CSVにメタ規則を設定していれば、その部分を除いた本文です。
- メタも保持・編集する処理では`load_document()`→`save_document()`を使います。メタと本文は同じファイルのスナップショットから返し、一つのファイルとして排他・原子的保存を行います。
- メタ付きCSVの`save()`は誤ってメタを省かないようエラーにします。通常CSVは設定しなければ従来どおりです。
- JSONLの従来の`RowsRepository.save()`は本文からファイル全体を作り直し、利用者メタを引き継ぎません。`load()`→`save()`でメタを保持できるとは扱わないでください。
- JSONLの本文への追記は`append_jsonl()`、固定ファイルサービスなら`append()`です。CSVの追記は提供しません。
- 既存の独自RowsSerializerは従来どおり使えます。文書APIへ対応する場合だけ、`loads_document` / `dumps_document`の追加契約を実装します。

実行例は`python -m examples.metadata`です。4種類の出力を見比べられます。入力例と出力見本は[sample_outputs/metadata](../sample_outputs/metadata)、テストは[メタ情報の回帰テスト](../tests/test_document_metadata.py)です。

窓口の共通規則と版変換付きの構成は[FILE_INTERFACES.md](FILE_INTERFACES.md)にまとめています。


追加ヘッダ・半角スペース区切り・modelsの設定と単独の版変換例は、[ヘッダと版変換の実行例](HEADERS_AND_SAMPLES.md)を参照してください。


CSV設定の全項目・条件とa〜gの例は[CSV設定ガイド](CSV_OPTIONS.md)を参照してください。


JSONL・KV・BlockRowsの設定整理と移行方法は[各形式の設定](FORMAT_OPTIONS.md)を参照してください。

YAMLも同じRowsDocumentの入口を使います。saveはルートlist、save_documentはmetadata/rows文書です。loadとload_documentは両方を読み込めます。詳しくは[YAML Rows](YAML_ROWS.md)を参照してください。
