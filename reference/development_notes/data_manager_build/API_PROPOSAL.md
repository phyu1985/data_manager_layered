# 公開APIと現在の実装

2026-10-30 / JSON・JSONLの最初の実装。
以前のtype/dataで包む提案を撤回し、ユーザー合意に従って平坦なtypeキーを採用する。

## 合意した方針

- 復元するモデル型はRepository生成時に固定する。
- 利用側はBaseModelのクラスを指定し、文字列tagのRegistryを管理しない。
- 単一モデル・dictには行tagを要求しない。
- 混在JSONLのtagは通常のキー名type。変更可能とし、業務フィールドへの上書きを防ぐ。
- dict / list[dict]はmodel=dictで明示する。
- 既存のtag形式との互換性は必須にしない。

## 公開の入口

```python
objects = ObjectRepository[User](model=User, base_dir=Path("data"))
objects.save("user.json", user)
user = objects.load("user.json")  # User

single = RowsRepository[User](model=User, base_dir=Path("data"))
single.save("users.jsonl", users)
users = single.load("users.jsonl")  # list[User]

mixed = RowsRepository[User | Event](model=(User, Event), base_dir=Path("data"))
mixed.save("events.jsonl", [user, event])
rows = mixed.load("events.jsonl")  # list[User | Event]
mixed.append_jsonl("events.jsonl", new_rows)

objects = ObjectRepository[dict[str, Any]](model=dict, base_dir=Path("data"))
rows = RowsRepository[dict[str, Any]](model=dict, base_dir=Path("data"))
```

Objectのsaveは1件、RowsのsaveはSequence、append_jsonlはIterableを受け取る。
現在の組み込み拡張子はObjectが.json、Rowsが.jsonlのみ。

## 型の自動判別とcast

混在JSONLでは、行のtypeを、生成時に指定したクラスの対応表と照合する。
選んだクラスのmodel_validateで検証し、実際のインスタンスを生成する。
未知のクラスをファイルからimportしたり、形が似たモデルを推測したりしない。

返却型はlist[User | Event]。各要素はisinstanceで絞り込む。
利用側でcastする必要はない。内部のcastは、JSON解析結果の辞書型や、
実行時に確認済みの具体型とジェネリック型の関係を型検査器へ伝える箇所に限る。
castを値の変換・検証・インスタンス生成には使わない。

単一モデルでは、指定されたモデルで全行を検証する。
混在時のジェネリック型引数User | Eventは明示する。

## JSONLの形式

```json
{"__meta__":{"schema_version":1,"mode":"mixed","models":["Event","User"],"tag_field":"type"}}
{"type":"User","id":"u1","name":"Alice"}
{"type":"Event","id":"e1","message":"started"}
```

- メタは先頭の非空行。schema_version、mode、models、混在時のtag_fieldを検証する。
- 単一モデルのmodeはsingle、dictはdict。本文にはtagを追加しない。
- mixedのtypeはSerializerが追加・除去する。モデルのフィールドではない。
- 既定はクラス名。重複は生成時にエラー。
- 固定名はJsonlSerializer(model_tags={User: "user", Event: "event"})で指定できる。
- tag_field="record_kind"のようにキー名を変更できる。
- 通常フィールドと出力aliasの衝突は生成時、計算フィールド等の動的な衝突は保存時に検出する。
- 未登録の派生モデルを親モデルとして黙って保存しない。
- dictモードでは混在モデル用ファイルを読み込まない。型情報を捨てないための初期制約。

メタなしの外部JSONLを読むときは、JSONLLoadOptions(metadata="absent")を明示する。
これは「メタなしと分かっている入力」を指定する設定であり、先頭行の内容による自動推測ではない。
mixedはメタ必須。全件保存では外部読み込み設定にかかわらず、常に内部形式のメタを出力する。
したがって外部入力用Serializerは読み込み用途とし、内部保存を再読する際は既定設定を使う。

## モデル変換・設定

専用の設定dataclassは担当Serializerが保持し、Repositoryは設定辞書を作らない。

```python
JsonSerializer(dump_options=JsonDumpOptions(by_alias=False, indent=2))
JsonlSerializer(
    dump_options=JSONLDumpOptions(by_alias=False),
    load_options=JSONLLoadOptions(metadata="required"),
)
```

- 既定はフィールド名出力。空文字とNoneを区別する。
- モデルのextra設定に従い、未知キーを独自に削除しない。
- aliasの受理はPydanticのモデル設定に従う。自動の逆引きはない。
- aliasを定義したモデルをフィールド名で往復させるには、モデル側で名前入力を許可する。
  Pydantic 2.7互換の例はConfigDict(populate_by_name=True)。
- serialization_aliasだけを指定してby_alias=Trueにした場合、入力側にも対応する設定が必要。
- 辞書のトップレベルキーはstrを要求する。値の表現範囲はJSONの規則に従う。
- NaNや任意のPythonオブジェクトを無条件に文字列化しない。
- エラーはRAISEのみ。失敗行を黙ってスキップしない。

## 内部構成と読む順序

```text
src/data_manager/
    repositories.py       # I/Oと変換の順序、Object / Rows
    file_io.py            # sidecarロック、一時ファイル置換、末尾読み取り
    model_conversion.py   # 型の固定、辞書化、検証
    errors.py             # 設定エラーと形式エラー
    serializers/
        json.py           # JSON解析・生成と専用設定
        jsonl.py          # 行・メタ・型判別と専用設定
```

ModelBindingは内部の型情報保持であり、利用側の公開Codecではない。
RepositoryのloadからSerializer.loads、ModelBinding.decodeへ追えば処理が分かる構成にする。
個々の業務フィールド名をRepositoryやSerializerへハードコードしない。

## 排他と追記

- 読み書きともsidecarをportalockerでロックし、失敗時のno-opフォールバックを設けない。
- loadはロック中にファイルを読み、そのスナップショットを検証する。
- saveは入力をシリアライズしてから、ロック中に一時ファイルを置換する。
- 現在は既存文書とマージしないJSON / JSONLなので、シリアライズ前のファイル読み取りはない。
  YAML移植時には既存読み込みからマージ・保存まで排他範囲を広げる。
- appendは全バッチを検証後、1回のロック内で新規判定、メタ検査、末尾検査、追記を行う。
- 新規はメタと本文をまとめて原子的保存。既存への直接追記は全件置換ほどの保証を持たない。
- I/O障害や異常終了時に不完全な末尾が残り得る。検出したらエラーにし、自動削除しない。
- メタと末尾の検査だけであり、途中の全行を再検証するものではない。
- 完全な最終行で改行だけがない場合は区切り改行を補う。
- 空appendは何も変更しない。空の内部JSONL作成はsave([])で行う。
- 保存先未存在のloadはFileNotFoundError。空一覧に変えて隠さない。

## 次に進める範囲

CSV、YAML、独自v0テキスト、Waveformは既存の形式固有処理を検証して順次移植する。
YAMLの文書マージ・コメント保持のため、ObjectSerializerの契約は拡張が必要。
CSVはネスト・配列・空欄・列名の仕様を明示してから実装する。
独自v0は値を文字列化する現実装を、任意型の往復対応として引き継がない。

Excel帳票の生成はexcel_reportsへ残す。保存モデルを帳票モデルへ変換する境界は利用側に置く。
すべての保存モデルへitems/titleを要求しない。Excel保存の共通化はまだ実施していない。
