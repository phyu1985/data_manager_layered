# 帳票出力：設計方針・インターフェース仕様

**版:** 統合版 v1.0.0（2026-10-30）  
**対象:** Python 3.12、Pydantic v2、openpyxl 3.1系、`.xlsx`  
**状態:** 本配布版の実装に対応する仕様。過去の「設計実装ガイド v2.3」に代わる現行版。

## 1. 目的と方針

`Record` を1件1行、可変長の `Record.items` を1 Itemにつき1列～複数列のブロックとして横方向へ出力する。業務担当者がExcelで書式を編集できることと、少人数で数年単位の保守ができることを重視する。

**採用する原則**

1. **業務データと表示を分離**。ドメインのフィールド名・値はモデル側、帳票の列選択・位置・表示名・フィルターは設定側。
2. **抽出条件・出力対象Item・見出し文字列を独立**。`conditions`（Recordの採否）、`item_keys`（どのItem種類を表示するか）、`item_titles`（何と表示するか）。
3. **コード方式とテンプレート方式はデータ整形だけ共有**。どちらも`project()`が`WorkbookData`を作り、Excelのセル操作は描画処理に閉じ込める。
4. **暗黙のI/Fをなくす**。`ReportItem.title`、`ReportRecord[TItem].items`を共通のPydantic基底クラスで保証する。
5. **誤った設定はExcel描画前に検出**。不正なフィールド・キー重複・型不一致・上部情報の不一致は例外。
6. **実装規模を最小限に保つ**。現状不要なRepository、DIコンテナ、テンプレート式評価器、プラグイン機構を作らない。

## 2. アーキテクチャ

```text
業務データ（Record / Item）         帳票定義
    |                                |----------------------|
    |                            ReportSpec            Excel __report__
    |                                |                      |
    |                                |                  template.load_template()
    |                                |                      |
    +----------------------+---------+----------------------+
                           |
                           v
                     project.project()
                  ・I/F／フィールド検証
                  ・ソート（任意、元データ不変更）
                  ・Record/Item条件によるRecord抽出
                  ・共通上部値の整合性検証
                  ・Itemキーと表示位置の照合、欠損補完
                           |
                           v
                      WorkbookData
                           |
             +-------------+--------------+
             v                            v
      excel.render_code()         excel.render_template()
       新規ブック作成             見本セル複製・値挿入
             |                            |
             +--------------+-------------+
                            v
                    openpyxl Workbook
                            |
                   呼出元で workbook.save()
```

| モジュール | 責務 | 扱わないこと |
|---|---|---|
| `contracts.py` | Record / Item共通基底、必要な属性の型 | 業務の固定項目、Excelセル番地 |
| `models.py` | 条件・表示指定・Excel非依存の出力値 | セル装飾や配置 |
| `project.py` | 入力検証、フィルター、Item照合、データ行・上部値組立 | openpyxlの操作 |
| `template.py` | `__report__`設定、テンプレート目印の解析、配置情報 | 業務条件の真偽判定 |
| `excel.py` | セル書き込み、ブロック・行・書式の複製、結合 | Recordの採否判断 |
| `api.py` | 公開窓口、モデルI/Fの検証、処理順の統括 | 業務用モデルの生成 |

## 3. 必須インターフェース

```python
class ReportItem(BaseModel):
    title: str  # Itemを識別する照合キー。空文字を許可しない。

class ReportRecord(BaseModel, Generic[TItem]):
    items: list[TItem]  # 未指定で空リスト。1レコード内の可変数Item。
```

業務側の定義例：

```python
class MeasurementItem(ReportItem):
    temperature: float | None = None
    voltage: float | None = None

class EquipmentRecord(ReportRecord[MeasurementItem]):
    record_id: str
    department: str
```

`ReportGenerator(EquipmentRecord, MeasurementItem)`の初期化で、`ReportRecord`/`ReportItem`継承と、Recordが宣言している`items: list[...]`の型が指定Item型と整合するか確認する。**このバージョンでは既存のBaseModel直接継承モデルは受理しない**。具体的な型の違いは静的型チェックと実行時の両方で検出する。

`items`が空でもRecordは有効。`title`は位置順で出力する場合もI/Fとして必須。`title`や各業務項目は通常の`model_fields`であることが必要。任意の`@property`は帳票設定から直接読み取れない。`@computed_field`を含む特別なケースは別途実装確認すること。

`Record`が実際の業務ドメインに紐づき、共通I/Fへの継承が不適切なら、UseCase層で帳票入力専用のRecordへ変換する。

## 4. データモデルと規則

### 4.1 帳票定義

| 型 | 主要項目 | 意味 |
|---|---|---|
| `Comparison` | `source`, `field`, `op`, `value` | 1つの比較。sourceは`"record"`または`"item"`。省略時はItem |
| `SheetSpec` | `name`, `logic`, `conditions` | シート名と、Recordを採用する条件 |
| `SheetSpec` | `headers`, `record_columns`, `item_columns` | 上部共通値／Recordの一覧列／1 Item分の一覧列 |
| `SheetSpec` | `item_title_field`, `item_keys`, `item_titles` | 照合対象フィールド／Item種類／Excel表示名 |
| `ReportSpec` | `sort_field`, `descending`, `sheets` | 共通ソートとシート設定一覧 |
| `WorkbookData` | `sheets` | 描画方式に依存しない出力結果 |

抽出条件の**評価対象となるフィールド**と、**Excelに出すフィールド**は異なってよい。

### 4.2 Recordの採否（AND/OR）

シートごとに1種類の論理演算子を選ぶ。条件内のAND/ORの入れ子は扱わない。

- **AND**：すべてのRecord条件が成立し、かつItem条件がある場合は**同じ1件のItem**がすべてのItem条件を満たす。
- **OR**：Record条件のいずれかが成立、または**いずれかのItem**がItem条件のいずれかを満たす。
- Recordが採用されたら、**条件を満たしたItemだけでなく、そのRecordのItem全体を照合対象にする**。ただし列に表示するのはそのシートで指定された`item_keys`だけ。
- 各シートは独立。ひとつのRecordが複数シートに出ることがある。どの条件にも合わなければ出力しない。

| 条件構成 | `items=[]`のとき |
|---|---|
| Record条件だけ（ANDまたはOR） | Record条件が成立すれば採用 |
| Item条件だけ | 不採用 |
| RecordとItemのAND | Item条件が成立しないため不採用 |
| RecordとItemのOR | Record条件が成立すれば採用 |

`None`のフィールド値は`!=`も含め比較結果を`False`にする。比較値そのものに`None`は指定不可。比較不能な型の組み合わせはエラー。同じItem内のANDを別Item間の寄せ集めで成立させない。

### 4.3 Itemの配置方式

**タイトル照合方式（推奨、テンプレート方式の既定）**

- `item_title_field="title"`：Itemから取り出す照合対象。
- `item_keys=["初期測定", "最終測定"]`：このシートで使うItem種類。位置を決める。
- `item_titles=["初回", "最終回"]`：同じ位置で表示する見出し名。
- タイトルの順序がバラバラでも、各Itemはキーの位置へ配置される。中間が欠けても空欄のまま。
- このシートに存在しないキーは**正常な非表示データとしてスキップ**する。帳票全体に存在しないキーでも同様。業務として正しいキーかの検証は、業務データ側の責務。
- 同一Record内で「このシートに表示するキー」が重複したらエラー。`item_keys`の重複、`item_keys`と`item_titles`の長さ不一致もエラー。
- 1 Itemあたりの列数はそのシートの`item_columns`の数。Itemが存在しない位置はその列数分すべて`None`にする。
- そのシートのRecordが0件でも定義されたキーの枠はすべて残す。

**位置順方式（Python定義で任意選択）**

- `item_title_field=None`、`item_keys=None`。各RecordのItemをソート結果（ソートなしなら入力順）に従って左から詰める。
- 必要数の見出しが足りなければエラー。Itemが0件なら最低1枠だけ残す。
- 同じ業務段階の途中欠損でも左詰めされるので、固定の測定段階にはタイトル照合方式を推奨。

### 4.4 ソート

`sort_field: str | None` は全シート共通。`None`ならItemの元の順序を維持。指定時はRecord単位で安定ソートする（同値は元順維持、値`None`は昇順・降順とも最後）。**Recordの行順は入力順**。モデルインスタンスの`items`を破壊的に並べ替えない。タイトル照合方式の表示位置はソートに依存しない。

### 4.5 上部共通値と0件時

`SheetSpec.headers` はRecordのフィールドから取得し、**そのシートで採用されたRecord全件が同じ値を持つこと**を検証する。異なる場合はエラー。採用Recordが0件なら共通値は`None`、見出しは残す。テンプレート方式は上部`{{header:field}}`の指定位置に出力する。

採用Recordが0件ならデータ行を増やさず、見本セルのフィールドマーカーだけを消す（書式と見出しは残す）。Itemの列はタイトル照合方式なら設定された列数、位置順方式なら最低1枠を保つ。

## 5. 出力方法

**Python方式**：上部情報をA列（キー）／B列（値）に上から並べ、直下に2行の見出し。Record見出しは縦結合、Itemの上段はItemブロック幅で横結合。Record行はその下に1件1行。利用側は`ReportGenerator.code(records, spec)`。

**Excelテンプレート方式**：`__report__`とセルマーカーを読み取り、見本のItemブロックを横複製してから見本のRecord行を下複製し、値を書き込む。利用側は`ReportGenerator.template(records, path)`。結果から`__report__`は削除する。設定仕様は[TEMPLATE_SPEC.md](TEMPLATE_SPEC.md)。

どちらも`ReportGenerator.prepare(records, spec)`で得られる`WorkbookData`の内容を使用する。出力ファイルの保存は呼び出し元の責務。

## 6. エラーと制約

- 不正な`Comparison.source`や演算子はPydanticで検証する。
- 存在しない条件・出力フィールド、タイトル重複、見出し数不足、Record/Item実体の型違い、上部値不一致は`ReportError`。
- `ReportGenerator`のモデルI/F違反は`TypeError`。`ReportItem.title`の欠落・空文字はPydantic検証エラー。
- テンプレート展開先の既存値や結合セルは上書きせずエラー。**右側と下側は空白を維持**する。
- テンプレートの画像・グラフ・テーブル機能・外部データ接続・名前定義・印刷範囲を含む複雑な構造の完全な移植・拡張は保証しない。
- 外部ブックのリンクは`load_workbook(..., keep_links=False)`で引き継がない。外部接続等は別途Excelで点検する。
- Excelの完成帳票に対する保存処理・権限・バックアップ・業務データ取得はライブラリ外部の責務。

## 7. 変更の受入基準

コード修正時は以下を確認する。

1. モデルI/Fが正しく、不正な組み合わせが生成時に検出される。
2. Record/Item条件のAND/ORが表の規則を満たす（Item空の場合を含む）。
3. 各Itemタイトルが表示指定キーの列へ配置され、途中の欠損が空欄になる。
4. 列に表示しないItemを含んでいても他の列へ詰まらず、Record抽出条件ではそのItemを評価できる。
5. コード方式とテンプレート方式の出力データの意味が等しい。
6. 見本行のExcel数式が複製され、ユーザーデータの`=`始まりは数式として実行されない。
7. テンプレートをExcelで実際に開き、書式・印刷・外部参照警告を確認する。
8. `python -m pytest -q`を通し、Gitの差分で既存の独自機能が失われていないことを確認する。

## 8. v2.3設計書からの主な改訂

- 「Item条件によるANYのみ」から「Record条件＋Item条件」の評価へ拡張。
- 「Itemは必ず左詰め」から、固定キーの位置への照合配置を追加（テンプレートで既定）。
- Itemの見出しを照合キーから独立させ、シートごとに表示対象Itemを変更可能にした。
- ソートを必須から任意に変更。
- 必須のデータI/Fを`ReportItem`/`ReportRecord[TItem]`として明示。既存の`BaseModel`だけのクラスとは互換ではない。
- `items=[]`のRecordをRecord条件によって採用可能にした。

以上は本リポジトリ内のコードから確認できる仕様です。独自GitHub版の設定列追加（例：`__report__!K:P`）は本配布版では扱っていません。
