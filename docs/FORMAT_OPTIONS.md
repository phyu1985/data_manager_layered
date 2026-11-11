# JSONL・KV・BlockRows：関連する指定をまとめる

## 実行例

```powershell
python -m examples.format_options outputs/format-options
```

sample_jsonl / sample_kv_values / sample_kv_pairs / sample_blocksに設定と入出力を分けています。既存のexamples/versioned_csv.py、versioned_rows.py、versioned_files.pyも新しい指定に揃えました。保存形式・tag名・メタの構造は変更していません。設定APIは以下の生成方法へ移行が必要です。

## JSONL：通常モデルとdict文書を別の入口で指定

```python
JsonlSerializer()
JsonlSerializer.for_models(model_tags={Measurement: "measurement", Note: "note"})
JsonlSerializer.for_dict(document_models=("Reading",))
```

| 入口 | 選ぶ場合 |
|---|---|
| 通常のコンストラクタ | Repositoryで指定したモデルから型名を自動生成する |
| for_models | 通常モデルへ長期保存用の固定tagを与える |
| for_dict | VersionedRowsなど、モデル生成前のdict文書へ固定識別名を与える |

for_modelsとfor_dictを一つの呼出に混ぜません。document_modelsは動的importやモデル復元の指定ではなく、dict文書の識別名です。for_dict()と名前を省略すればmodels=[]になり、通常モデルを持つRepositoryへの接続は拒否します。

現在モデルの登録と版変換をまとめる場合は、[VersionedRowsRepository.for_models](VERSIONED_ROWS.md)を使います。
この入口ではJSONLのmodelsも登録表から構成するため、document_modelsを別に手書きする必要はありません。

設定時には固定名の空欄・重複、接続時には許可モデルとの対応・tag衝突を確認します。実データのtag不足・未知tag・モデル値は読取時、出力データのtag衝突は保存時に確認します。確認対象が異なるため残します。

内部は「対応表を準備 → メタを照合/生成 → 各行を変換」という順です。全件のloads_document / dumps / dumps_documentでは対応表を一度だけ作り、メタと全行で共有します。行ごとの対応表の再構築は行いません。Serializerを複数Repositoryで共有できるよう、操作をまたいだ共有キャッシュは持ちません。

追記用のserialize_metadata_line / serialize_data_linesなどは単独でも呼べる入口なので、それぞれで必要な準備を行います。JSONLDumpOptions / JSONLLoadOptionsは引き続き使います。required / absentは読込形式の選択であり、absentは読取専用です。全件保存と追記にはrequiredの構成を用意します。absentで混在モデルを読むことも拒否します。

## KV：モードとキー一覧を別々に指定しない

```python
options = KvOptions().with_value_header(
    ("saved_at", "version", "saved_path"), skip=1,
)
options = KvOptions(key_value_separator=" ").with_key_value_header(skip=1)
```

| 方法 | 読み方 |
|---|---|
| KvOptions() | コメントから値を取り込まない通常KV |
| with_value_header(keys, skip=...) | コメントの値へ順番に名前を付ける |
| with_key_value_header(skip=...) | コメントに記載されたキーと値を読む |

本文の記号は通常の引数、ヘッダ方式は生成メソッドで指定します。キー一覧とheader_layoutを同時に組み立てる必要はありません。空・重複キーやskipは生成時に確認します。

各メソッドは新しい不変設定を返し、元の設定は変更しません。dataclasses.replaceで本文設定を変更しても選択済みのヘッダを保持します。先頭コメントの収集、本文の読取、ヘッダの解釈と合流を分けています。

header_keys / header_layout / header_skipは確認用の読み取り専用propertyで、コンストラクタの引数ではありません。_header_keysなどの非公開項目は直接指定しないでください。

入力専用のヘッダ設定で標準KVへ保存することは従来どおり拒否します。読み込んだモデルを、既定のKvSerializerを持つ別の保存先へ渡して正規化します。元の説明コメントの配置は再現しません。

## BlockRows：一行の情報を一か所で宣言

```python
options = BlockRowsOptions(rows=(
    BlockRow.root("id"),
    BlockRow.items("attrs", "name", "value", header=("old_name_1", "old_value_1")),
    BlockRow.items("attrs", "name", "value", header=("old_name_2", "old_value_2")),
    BlockRow.root("length"),
))
```

| 一行の項目 | 役割 |
|---|---|
| columns | 復元先のキー。root / itemsの位置引数で指定 |
| target | Noneはモデル直下、名前があればその一覧へ一要素を追加 |
| header | 保存時の見出し。省略時はcolumnsを使う |

BlockRowは、一行に対応する三つの情報を表す設定です。方式ごとの基底クラスやオプションの階層は追加していません。

各行の列名・見出しの個数・所属先はBlockRowの生成時、全行の直下キーと一覧名の衝突はBlockRowsOptionsで確認します。columns / row_targets / header_columnsという三つの配列の順番を人が合わせる必要はありません。

三つの名前は内部の文法処理向けの読み取り専用propertyとして残します。生成時にはrowsを指定します。rows=Noneはファイルの列定義を採用する読込用です。書込には行定義が必要です。

繰り返し一覧の必要件数はitemsの行数から決まります。宣言と保存する要素数が一致しなければエラーです。ファイル由来の列構成・実レコードの形・モデル値は、読書き時に確認します。

## BlockRowsのファイル全体メタもCSVと共通

```python
options = BlockRowsOptions(
    rows=(BlockRow.root("name", "value"),),
    metadata=CsvKeyValueHeaderOptions.until_marker("[columns]").as_text(multiple=True),
)
```

metadataにはCSVと同じCsvHeaderOptions / CsvKeyValueHeaderOptionsを渡します。メタ専用の追加クラスは作っていません。BlockRows側のmarkerは各レコードの区切り、metadataの終端はファイル全体メタと列定義の境界です。

メタの空値の扱いはmetadata側のempty_as_none、本文はBlockRowsOptions.empty_as_noneで独立に指定します。load_document / save_documentのRowsDocument(metadata, rows)は従来どおりです。

## 移行表

| 直前の指定 | 今回の指定 |
|---|---|
| JsonlSerializer(model_tags=...) | JsonlSerializer.for_models(model_tags=...) |
| JsonlSerializer(document_models=...) | JsonlSerializer.for_dict(document_models=...) |
| KvOptions(header_keys=..., header_skip=...) | KvOptions().with_value_header(..., skip=...) |
| KvOptions(header_layout="key_value", header_skip=...) | KvOptions().with_key_value_header(skip=...) |
| BlockRowsOptions(columns=..., row_targets=..., header_columns=...) | rows=(BlockRow.root(...), BlockRow.items(...), ...) |
| metadata_marker / metadata_separator / metadata_prefix / metadata_multiple | metadataへ共通ヘッダ設定を渡す |

JSONL・KVには設定用クラスを追加していません。BlockRowsでは一行の定義であるBlockRowだけを追加しました。必要な入力検証・保存保護は残し、指定方法の組合せ確認と操作内の重複を減らしています。
