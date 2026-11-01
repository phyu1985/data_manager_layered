# Pydantic + openpyxl 帳票出力

**統合版 v1.0.0 / Python 3.12 / Pydantic v2 / openpyxl / Excel `.xlsx`**

`Record`（1件＝Excelの1行）と `Record.items`（1 Item＝複数列のブロック）を、シートごとに抽出・整列して出力する小さな実装です。2～3人による長期保守を想定しています。

## 1. できること

- **2つの出力方法**：Python側でレイアウトを作る `code()` と、既存Excelを雛形にする `template()`。
- **Record / Item別の抽出条件**：`record.department` や `item.temperature` 等でRecordをシートへ振り分け。比較演算子は `== != < <= > >=`。
- **条件・Item選択・見出しを分離**：`conditions` はRecordを出すか、`item_keys` はシートに表示するItemの種類、`item_titles` は見出しの表記。
- **途中欠損でも左詰めしない**：Itemの `title` と設定キーを照合するため、初期・最終だけのRecordでも中間列は空欄。
- **Itemsが0件のRecordも表示可能**：Record条件が成立すればRecord行を残し、Item欄は空欄。
- **ソート任意**：全シート共通のItemソートを指定可能。`sort_field=None`（テンプレートB1空欄）ならソートしない。
- **最小共通I/F**：`ReportItem.title` と `ReportRecord[TItem].items` を基底クラスで保証し、`ReportGenerator`生成時に型の組み合わせを検証。
- **テンプレートの見本行を複製**：Itemブロックは右へ、Record行は下へ。基本書式とブロック内の結合をコピー。テンプレート数式（例：`ROW()`）を維持。
- **外部ブックリンクを持ち込まない**：テンプレート読み込み時に `keep_links=False` を設定。

仕様・制約・責務の詳細：**[docs/DESIGN.md](docs/DESIGN.md)**  
Excel定義のセル配置：**[docs/TEMPLATE_SPEC.md](docs/TEMPLATE_SPEC.md)**  
変更履歴：**[CHANGELOG.md](CHANGELOG.md)**

## 2. セットアップと実行

フォルダ `simple_excel_reports` に移動して実行します。

```powershell
python -m pip install -r requirements.txt
python example.py
python -m pytest -q
```

`python example.py` は、次の3ファイルを生成します。

| ファイル | 内容 |
|---|---|
| `帳票テンプレート.xlsx` | 編集できるExcelの雛形。`__report__`を含む |
| `帳票_コード方式.xlsx` | `ReportSpec`から作る新規ブック |
| `帳票_テンプレート方式.xlsx` | Excelの雛形から作る完成帳票。`__report__`は出力時に削除 |

**注意**：`example.py`は同名のサンプルテンプレートを毎回作り直します。自分で編集したファイルを同名で保存しないでください。

## 3. 業務用モデルの作り方（必須I/F）

```python
from reporting import ReportGenerator, ReportItem, ReportRecord


class MeasurementItem(ReportItem):
    # title: str は基底クラスから継承。
    temperature: float | None = None
    voltage: float | None = None


class EquipmentRecord(ReportRecord[MeasurementItem]):
    # items: list[MeasurementItem] は基底クラスから継承。
    record_id: str
    department: str


records = [
    EquipmentRecord(
        record_id="R001",
        department="製造課",
        items=[
            MeasurementItem(title="最終測定", voltage=110),
            MeasurementItem(title="初期測定", voltage=100),
        ],
    ),
    EquipmentRecord(record_id="R002", department="製造課"),  # items=[]
]

generator = ReportGenerator(EquipmentRecord, MeasurementItem)
```

`title` は**Item種類の照合キー**であり、Excelの表示文字列とは別です。空文字は不可。`items`は省略すると新しい空リストになります。`record_id`などの業務項目は強制していませんが、帳票設定が参照するフィールドはPydanticモデルの正式なフィールドとして定義してください。`@property`だけの値は現行の `_get()` では読みません。

業務ドメインが帳票ライブラリに依存すべきでない場合は、既存ドメインから上記の「帳票用モデル」に変換して渡してください。

## 4. Python定義で出力する

```python
from reporting import Column, Comparison, ReportSpec, SheetSpec

spec = ReportSpec(
    sort_field=None,  # 並べ替えなし（titleにより出力位置が決まる）
    sheets=[
        SheetSpec(
            name="電圧一覧",
            logic="AND",
            conditions=[
                # Itemが0件でもRecord条件が合えば行を出す。
                Comparison(source="record", field="department", op="==", value="製造課"),
            ],
            record_columns=[Column(field="record_id", label="管理番号")],
            item_columns=[Column(field="voltage", label="電圧")],
            item_title_field="title",
            item_keys=["初期測定", "最終測定"],
            item_titles=["初回", "最終回"],
        )
    ],
)

workbook = generator.code(records, spec)
workbook.save("out_code.xlsx")

# セルを作る前にRecordの抽出結果を確認できる。
projected = generator.prepare(records, spec)
print(projected.model_dump())
```

上記でR001は「初回=100／最終回=110」、R002は「初回・最終回が空欄」になります。`ReportGenerator.template()`ではPythonの`spec`は使わず、Excelの`__report__`から同等の設定を作ります。

## 5. Excelテンプレートで出力する

```python
# Excel雛形のレイアウトと__report__を使用。
workbook = generator.template(records, "帳票テンプレート.xlsx")
workbook.save("out_template.xlsx")  # 元の雛形とは別名で保存
```

雛形には`__report__`という設定シートが必須です。抽出条件はA～E列、Itemの照合キー・見出しはG～J列。例：

**抽出条件**

| sheet | logic | field | operator | value |
|---|---|---|---|---|
| 電圧一覧 | AND | record.department | == | 製造課 |

**出力列**

| sheet | position | title（表示名） | key（Item.titleと一致） |
|---|---:|---|---|
| 電圧一覧 | 1 | 初回 | 初期測定 |
| 電圧一覧 | 2 | 最終回 | 最終測定 |

出力シート側には、`{{header:department}}`、`{{record:record_id}}`、`{{item:voltage}}`、`{{item_title}}` を配置します。**実際の雛形作成規則・設定セル位置・数式の注意点は [docs/TEMPLATE_SPEC.md](docs/TEMPLATE_SPEC.md) を参照してください。**

## 6. フォルダ構成と担当

```text
simple_excel_reports/
├── reporting/
│   ├── contracts.py   # ReportItem / ReportRecord の共通I/F
│   ├── models.py      # 条件設定・出力値モデル
│   ├── project.py     # 検証・Record抽出・Item照合・値の組み立て
│   ├── template.py    # __report__ とExcelのマーカー読取
│   ├── excel.py       # コード方式／テンプレート方式のセル描画
│   ├── api.py         # ReportGenerator（公開窓口）
│   └── __init__.py
├── tests/
│   ├── test_report.py
│   ├── test_contracts.py
│   └── test_template_formula.py
├── docs/
│   ├── DESIGN.md
│   └── TEMPLATE_SPEC.md
├── example.py
├── requirements.txt
├── CHANGELOG.md
├── .gitignore
└── README.md
```

システムの配置先例：`UseCase`からこの`reporting/`の公開窓口を呼び出し、業務モデルを直接渡さない場合はUseCase側で帳票用Recordへ変換します。`View`は生成されたExcelファイルの保存先選択などを担い、`DataManager`・`DataStore`は帳票描画の責務を持ちません。

## 7. テスト・運用上の注意

- `python -m pytest -q`で検証。Pydanticのモデル制約、Record/Item混在条件、AND/OR、欠損、2シートの異なる表示キー、空Item、衝突、数式コピーを含みます。
- 条件に一致しなかったRecordはどのシートにも現れません。ひとつのRecordが複数シートに現れることは許容します。
- Recordが0件でもシートと見出しは生成します。**タイトル照合方式**では定義済みのすべてのItem枠を残し、**位置順方式**では最低1枠を残します。
- 外部リンクを引き継がなくても、複雑な図形・印刷領域・データ接続・名前定義のすべてを安全に維持または削除する保証はありません。実際のExcelで出力例を開いて確認してください。
- Excelテンプレートにある**数式は複製されます**が、複製先に合わせたセル参照の自動書き換えはしません。詳しくはテンプレート仕様書を参照してください。
- 本リポジトリは業務固有の設計・認証・アクセス制御・データ取得機能を含みません。実データや社内用テンプレートを公開リポジトリへ登録する際は社内規程を確認してください。
- ライセンスはこの配布版では未指定です。公開・再配布する際は権利関係とライセンスを別途決めてください。

**設計方針**：新しい抽象基底クラス・Repository・複雑な汎用テンプレート構文は追加しない。データ抽出は`project.py`、Excel操作は`excel.py`に分離し、機能追加はまず既存の境界内で行います。
