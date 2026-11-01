# DataManager redesign

Excel帳票側も含む実際のフォルダー配置は[FILE_LAYOUT.md](FILE_LAYOUT.md)を参照してください。

全体の流れ・構成・クラス・ロック・版互換は[ARCHITECTURE_GUIDE.md](ARCHITECTURE_GUIDE.md)のMermaid図で確認できます。

## 生データから再解析・帳票まで試す（v0.4.1）

[END_TO_END_GUIDE.md](END_TO_END_GUIDE.md)に、一連の利用手順と各モジュールの担当をまとめています。
[examples/end_to_end.py](examples/end_to_end.py)を実行すると、生データ読取→加工用Presets→初回保存→対象選択→解析保存→再解析保存→帳票出力を確認できます。
通常生成するデータファイルは設定YAML・測定JSONL・一形式の帳票の三つです。排他用.lockは別途生成されます。

```powershell
$env:PYTHONPATH = "src;."
.\.venv\Scripts\python.exe -m examples.end_to_end .\end_to_end_output
```


## 現在の入口（v0.4.0）

[READABILITY_REVIEW.md](READABILITY_REVIEW.md)に、単一責任・委譲・DRY・KISSの適用理由をまとめています。
[WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)が現在の使い方です。

```python
with analysis.edit() as presets:
    presets.threshold = 110
    analysis.save_settings(presets, overwrite=True)
```

管理用Editorをたどらず、用途別Presetsを直接扱います。
以下のv0.3系の節は変更経緯を含みます。APIが異なる場合は上記ガイドを参照してください。


BaseModelを中心とするファイル入出力の再設計です。JSON・YAML・CSV・JSONL・独自テキストv1・読み取り専用Waveformに対応しています。

## コーディングルール

[AGENTS.md](AGENTS.md)に、属性の公開範囲・命名・docstring・戻り値注釈・段落のルールを記録しています。

今回、生成時の引数名を`base_directory`、`serializers_by_extension`、`lock_timeout_seconds`へ変更しました。
初期実装の`base_dir`、`serializers_by_ext`、`lock_timeout`から呼び出し側も変更してください。
`load` / `save` / `append_jsonl`の操作名は共通です。独自テキストは型を保持するv1へ変更しています。

## 編集・初回保存・外部反映（v0.3.1）

[EDITING_AND_EXTERNAL_UPDATES.md](EDITING_AND_EXTERNAL_UPDATES.md)に今回の追加実装の意図と使い方をまとめています。
同じ解析フォルダの編集はwith analysis.edit()で保持し、保存はanalysis.save_settings(presets)等へ依頼します。
初回保存の失敗時は今回作成したデータファイルだけを削除します。
外部反映はExternalUpdateService.refresh()で保存済みの値から再実行できます。
実DBと画面のボタンは接続先のアプリで組み込みます。集約JSONの更新例は実行できます。

## 加工・解析・帳票への接続（v0.3.0）

最初に[WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)を読んでください。構成の意図・利点・呼び出し方・保証範囲をまとめています。
[examples/run_analysis_workflow.py](examples/run_analysis_workflow.py)が実行順、
[examples/analysis_workflow.py](examples/analysis_workflow.py)が用途別Presetsとアプリ側services、
[src/data_manager/versioning.py](src/data_manager/versioning.py)が辞書の隣接版変換です。

全件saveは既存ファイルを既定で拒否するようになりました。更新時だけoverwrite=Trueを明示してください。
旧版の全項目を保持する方式は採らず、維持対象と廃止対象をcast側で選びます。
古い設計文書と記述が異なる場合、今回の接続例とWORKFLOW_GUIDE.mdが現行の方針です。

## 最初に読むもの

- [MODEL_BOUNDARIES.md](MODEL_BOUNDARIES.md): Presets / Settingsの役割と、同じモデルを共用する判断（設計案）。
- [VERSIONING_DESIGN.md](VERSIONING_DESIGN.md): 版の更新ルールと旧版互換の検討記録（実装済みの範囲はWORKFLOW_GUIDE.md参照）。

- [SERVICES.md](SERVICES.md): ユースケースで使うservicesモジュールの構成例。
- [REVIEW_REPORT.md](REVIEW_REPORT.md): レビューで修正した問題と、未実装の設計提案。

- [FORMATS.md](FORMATS.md): 各形式の使い方、YAML合成、CSVの制約、波形の社内側接続。

- [API_PROPOSAL.md](API_PROPOSAL.md): 合意内容・公開API・現在の対応範囲。
- [src/data_manager/repositories.py](src/data_manager/repositories.py): 読む・保存する・追記する処理の順序。
- [src/data_manager/model_conversion.py](src/data_manager/model_conversion.py): モデルの辞書化とPydantic検証。
- [src/data_manager/waveform.py](src/data_manager/waveform.py): ヘッダー解析・復号を注入する波形専用の入口。
- [IMPLEMENTATION_REVIEW.md](IMPLEMENTATION_REVIEW.md): 元の実装を再利用・修正・廃止する理由。
- [DESIGN.md](DESIGN.md): 最初の検討記録。現行仕様はAPI_PROPOSAL.mdを参照。

## 実行

Python 3.12以上。Windows PowerShellで、このフォルダーを開いて実行します。
専用の`.venv`は作成済みです。別環境へ移す場合は先に仮想環境を作ってください。

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe example.py
.\.venv\Scripts\python.exe examples/application_services.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pyright
```

PyrightにはNode.jsが必要です。Pylance画面自体の検証ではなく、同系の型検査器で確認しています。
`typecheck/positive.py`で返却型とisinstanceの絞り込みを検証します。
`typecheck/negative.py`は誤った型の保存を3か所含むため、通常の検査対象から除外しています。
これを個別にPyrightへ渡した場合は、3件のreportArgumentTypeが期待結果です。
`typecheck/services_negative.py`も同様に3件の誤入力を検出し、サービス経由でも型制約を維持することを確認します。

## ユースケースで使う場合

[examples/application_services.py](examples/application_services.py)のように、アプリのservicesモジュールで保存先とRepositoryを一度だけ組み立てます。
ユースケースは`services.settings.load()`、`services.events.append(rows)`のように用途だけを選べます。
型変換・排他・例外は既存Repositoryへ委譲し、サービス側へ複製しません。

## 基本の使い方

```python
from pathlib import Path
from pydantic import BaseModel
from data_manager import ObjectRepository, RowsRepository

class User(BaseModel):
    id: str
    name: str = ""

class Event(BaseModel):
    message: str

users = ObjectRepository(model=User, base_directory=Path("data"))
users.save("user.json", User(id="u1"))
user = users.load("user.json")  # User

events = RowsRepository[User | Event](model=(User, Event), base_directory=Path("data"))
events.save("events.jsonl", [user, Event(message="started")])
rows = events.load("events.jsonl")  # list[User | Event]
```

混在JSONLは次の形です。型名の登録操作と、モデルへのtypeフィールド追加は不要です。

```json
{"__meta__":{"schema_version":1,"mode":"mixed","models":["Event","User"],"tag_field":"type"}}
{"type":"User","id":"u1","name":""}
{"type":"Event","message":"started"}
```

業務フィールドと`type`が衝突する場合はエラーにします。変更例:

```python
from data_manager import JsonlSerializer

events = RowsRepository[User | Event](
    model=(User, Event),
    base_directory=Path("data"),
    serializers_by_extension={".jsonl": JsonlSerializer(tag_field="record_kind")},
)
```

単一モデルの行にはtagを付けません。dictモードは`ObjectRepository[dict[str, Any]](model=dict, ...)`
または`RowsRepository[dict[str, Any]](model=dict, ...)`を使います。

## 処理の構造

```mermaid
flowchart LR
    A[Repository: パス・排他・I/O] --> B[Serializer: 形式の解析・生成]
    B --> C[モデル変換: 辞書化・検証]
```

Repositoryのloadを読むと、ファイル読み込み→形式解析→指定モデルの検証へ進みます。
モデル固有の項目名による分岐はありません。独自のalias逆引きや未知キーの削除もありません。

## 保証と現在の範囲

- ロックはportalockerによるsidecar方式。取得失敗時にロックなしへ切り替えません。
- 全件保存は同じディレクトリの一時ファイルを置換し、失敗時の一時ファイルも片付けます。
- 追記はバッチを検証した後、1回の排他範囲で新規作成または追記します。
- 追記中のI/O障害・異常終了で末尾が不完全になる可能性は残ります。自動修復は行いません。
- JSONL全件保存は常にメタを生成します。追記では既存メタを検査して保持します。
- JSONL追記は先頭と末尾を調べ、既存の中間行をすべて再検証する処理ではありません。
- 同じsidecarロックを使うプログラム間で排他します。
- クラス名を変更する長期保存用途では`JsonlSerializer(model_tags={User: "user"})`で固定名を指定します。
- 入力aliasと出力aliasの往復はモデル側の入力設定に従います。出力専用aliasを自動で入力名に変換しません。

**未実装:** Excel保存との結合、メタ情報取得API、修復API。
波形は社内側のheader_reader接続が必要です。実ヘッダー・実復号の結合検証は、合成テストとは別に実施してください。

元のコードは`../mhi/DataManager`、帳票側は`../excel_reports`を参照しています。

型検査の追加: typecheck/versioning_positive.pyで版変換後の戻り値型を確認します。
typecheck/versioning_negative.pyは意図したreportArgumentTypeを2件含みます。
