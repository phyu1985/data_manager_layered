# YAMLの一覧と版変換

`YamlRowsSerializer`はレコード一覧を扱います。拡張子は通常の`.yaml / .yml`で、
Object用と分ける拡張子は不要です。RowsRepositoryの既定登録に追加しています。

## 読み書きの入口

```python
repository = RowsRepository(model=Reading, base_directory=Path("data"))
rows = repository.load("rows.yaml")
repository.save("copy.yml", rows)
```

`save()`は次のルートlistを保存します。`load_document()`でも読め、その場合のmetadataは空辞書です。

```yaml
- name: A
  value: 1
- name: B
  value: 2
```

`save_document()`はメタ付きの文書を保存します。`load()`でも本文だけを取り出せます。

```yaml
metadata:
  version: 3
  title: Sample
rows:
  - name: A
    value: 1
```

```python
document = RowsDocument(
    metadata=ReportMetadata(version=3, title="Sample"),
    rows=[Reading(name="A", value=1)],
)
repository.save_document("report.yaml", document)
restored = repository.load_document("report.yaml", metadata_model=ReportMetadata)
```

メタが空でもsave_documentはmetadata/rowsの形を保ちます。
行はdictまたは単一種類のBaseModelで、子dict・子モデル・配列はYAMLの入れ子として保持します。
dictモードではYAML本来の数値・bool・日付などの型が使われます。数値に見える文字列は引用して記載してください。

## 役割と制約

- ObjectのYamlSerializerは、単一マッピング・テンプレート・既存コメントの合成を担当。
- YamlRowsSerializerは、listまたはmetadata/rowsの全件読み書きを担当。
- YAMLの解析、循環参照検出、通常値への変換はyaml_values.pyで共用。

Rows側は元の説明コメントや引用表現の保持、テンプレート合成、追記を扱いません。
空一覧は`[]`です。空ファイル・null・通常のObjectマッピングを空一覧へ読み替えません。
メタ付き文書はmetadataとrowsの2キーだけを受け入れ、余剰キーを黙って捨てません。
行のスカラー・不正なキー・循環エイリアス・対応していない値はエラーです。
モデルの出力も各行はdict、metadataはdictに限定し、読み戻せない形を保存しません。

必要なら`YamlRowsSerializer(by_alias=True)`を明示登録します。
メタのalias出力は既存の`save_document(metadata_by_alias=True)`を使います。
RowsRepositoryへ複数のモデル型を直接指定する方法は対応していません。
混在型を版付きで扱う場合は、dict用のRowsRepositoryと`VersionedRowsRepository.for_models`を組み合わせます。

## V2/V3だけを扱う場合

```python
converter = VersionConverter(
    current_version=3,
    upcasts={2: upcast_v2_to_v3},
    downcasts={3: downcast_v3_to_v2},
)
```

実際に通る経路だけを登録します。V0/V1の仮castは不要です。
V0/V1を読もうとすれば、未登録の変換経路としてエラーになります。

**版情報がないデータは、既定ではV0です。** V2なのかV3なのかを値の形から推測しません。
根拠のある別の判別方法があればVersionedRowsRepositoryのread_versionを指定し、
判別できなければエラーにしてください。版不明の入力を通すための仮castは作りません。
ルートlistだけのYAMLはmetadataがないため、この点に注意してください。

版付きの保存にはmetadata/rows文書を使います。メタと本文をまとめてcastし、
保存版の番号をメタへ記録します。現在のモデルの版ごとの定義は不要です。

## 実行例

```console
python -m examples.yaml_rows outputs/yaml-rows
```

架空の測定値を使う説明用サンプルです。各処理を別の関数にしています。

| 関数 | 内容 |
|---|---|
| sample_plain_list | 提示された形のルートlistの読み込み、.ymlへの保存 |
| sample_document | メタ付き文書の保存、型付きメタの復元 |
| sample_versioned_rows | V2のYAML→V3のモデル→V3保存→V2への別名保存 |

元のV2ファイルは上書きしません。入力・出力の再読と元ファイルのバイト列保持も確認します。

見本はsample_outputs/yaml_rowsに収録しています：[ルートlist](../sample_outputs/yaml_rows/rows.yaml)、[メタ付き](../sample_outputs/yaml_rows/document.yaml)、[V2入力](../sample_outputs/yaml_rows/v2.yaml)、[V3出力](../sample_outputs/yaml_rows/v3.yaml)、[V2再出力](../sample_outputs/yaml_rows/export_v2.yaml)。
