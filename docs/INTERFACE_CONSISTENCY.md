# Repository / Serviceの整合性と移行

通常・版付きRowsの基本操作を揃えました。メタを保持する処理は、文書として読み書きします。

| 操作 | RowsRepository / VersionedRowsRepository |
|---|---|
| load(path) | list[Row]を返す |
| save(path, rows) | Sequence[Row]を全件保存する |
| load_document(path) | メタと行をRowsDocumentで返す |
| save_document(path, document) | メタと行を一緒に保存する |

VersionedRowsRepositoryの型引数は`[Metadata, Row]`です。版付きのload_documentは構成済みの現在メタ型を返し、明示したmetadata_modelへ変換することもできます。
`load`もメタを検証してから行を返します。旧版を推測で読み飛ばす処理はありません。

## メタを保持する呼び方

```python
repository = VersionedRowsRepository.for_models(
    repository=raw_repository, converter=converter,
    metadata_model=CaptureMetadata, model_tags={Reading: "reading"},
)
document = repository.load_document("source.blocks")
repository.save_document("current.jsonl", document)
repository.for_version(0).save_document("export.blocks", document)
```

FileServiceで文書を扱う場合は、通常・版付きとも同じアダプターを使います。

```python
file = FileService(
    repository=RowsDocumentRepository(repository=repository, metadata_model=CaptureMetadata),
    path="current.jsonl",
)
document = file.load()
file.save_as("copy.jsonl", document)
```

RowsFileServiceも両Repositoryに対応します。load_document(metadata_model=CaptureMetadata)で型付きメタを取得し、省略時はdictで取得します。
VersionedRowsの追記は未対応なので、appendはConfigurationErrorです。版変換を追記で迂回しません。

## 行だけの保存とメタの省略

VersionedRowsのsave(path, rows, metadata=metadata)でメタを渡せます。
for_modelsで構成した場合、省略時は現在メタモデルの既定値を使い、版番号は現在版に揃えます。
必須メタを補えない場合は保存前に失敗します。既存ファイルのメタを自動で引き継ぎません。
メタを残す必要がある場合はload_document / save_documentを使ってください。

独自のdecode_current / encode_currentを接続する場合も、現在の文書はRowsDocumentです。
メタ省略時の既定値やdictメタの正規化が必要なら、コンストラクターへmetadata_modelを指定します。
for_modelsはこの指定も自動で行います。独自codecをメタ検証のため空の行一覧で呼ぶことはありません。

版付きのmetadata_by_alias=Trueは受け付けません。castの内部はフィールド名で統一し、旧版のメタ名はcastで変更します。
通常のRowsRepositoryでは引き続きmetadata_by_aliasを使えます。RowsDocumentRepositoryもこの方針へ委譲します。

## 型と例外

FileServiceは読取型と書込型を別々に推論します。listを読み、tupleを含むSequenceを保存できます。
手書きで型注釈を付ける場合は、`FileService[list[Reading], Sequence[Reading]]`と指定します。
型引数一つの場合は、従来どおり読取型と書込型を同じ型として扱います。

Object・Rowsとも、モデル検証の失敗はSerializationErrorで通知します。元のValidationErrorは例外の原因として残します。
ファイルが見つからない、ロック取得失敗などのI/O例外は従来どおりです。

現在モデル一つの版互換は`VersionedObjectRepository.for_model(repository=raw, converter=converter, model=Settings)`で構成できます。
維持項目を含む独自文書には、既存のdecode_current / encode_current方式を使います。

## 形式専用設定

- JSONのindentは有効です。JSONLは1件1行のためindentを設けず、内部はNone固定です。
- JSONLのensure_asciiは形式メタ・利用者メタ・本文へ同じように適用します。
- JSONLLoadOptions(metadata="absent")は読取専用です。保存・追記はrequiredの構成を別に用意します。
- YAMLのRowsにはYamlRowsDumpOptionsでby_aliasと字下げを指定できます。テンプレート・コメント保持の設定はObject側に残します。
- CSVのheader_line、comment_prefixes、strip_column_names、allow_trailing_empty_columns、empty_as_noneは読取専用です。by_aliasは出力専用です。
- CsvSerializerのread_options / write_optionsは、共通optionsの全体を置き換えます。項目単位のマージはしません。

実行例は`python -m examples.repository_interfaces outputs/repository-interfaces`です。

## 今回の確認

- 既存回帰テスト313件が通過。ケース数は増やさず、関連する既存ケースの確認を補いました。
- 版変換・YAML・共通I/Fなど9種類の実行例と、5種類の型誤入力確認が通過しました。
- 変更したPythonファイルと追加例のPyrightはエラー・警告とも0件です。
- 全体のPyrightには、この検証環境でExcel / pandas関連の既存49件が残ります。変更前後で指摘位置は同一です。

波形のバイト列読取のメソッド名や旧互換名の公開など、前回の優先度「低」の項目は今回変更していません。
