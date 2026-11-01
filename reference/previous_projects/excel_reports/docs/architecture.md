# 帳票出力の構成と呼び出し順

本書は現在の実装と、将来PySide6から呼び出す際の境界を示します。
GUI本体は未実装です。`report_service.py`まではGUIに依存せず実行できます。

## 図の記法

| 記法 | 用途 |
|---|---|
| `flowchart TD` | 構成・処理・分岐を上から下へ表示 |
| `flowchart LR` | データの関係を左から右へ表示 |
| `sequenceDiagram` | 呼び出し先を横に並べ、時間順に上から下へ表示 |

フローチャートの四角は処理・データ、ひし形は判断です。
シーケンス図の`->>`は呼び出し、`-->>`は応答、`loop`は繰り返し、
`alt/else`は分岐、`Note`は補足、`autonumber`はメッセージ番号です。

## 全体構成（flowchart TD）

```mermaid
flowchart TD
    UI["GUI・CLI：データとパターンを選択"]
    Models["report_models.py<br/>Record / Item"]
    Registry["report_patterns/registry.py<br/>固定ID・表示名・用途"]
    Service["report_service.py<br/>create_report"]
    Code["report_patterns/inspection.py・voltage.py<br/>新しいReportSpecを生成"]
    Template["templates/inspection_submission.xlsx<br/>条件・列・配置・書式"]
    API["reporting/api.py<br/>ReportGenerator"]
    Loader["reporting/template.py<br/>定義と配置を読み取る"]
    Spec["ReportSpec<br/>何を出力するか"]
    Place["Placement<br/>どのセルへ出力するか"]
    Project["reporting/project.py<br/>抽出・ソート・共通値検証"]
    Data["WorkbookData<br/>出力値と順序"]
    Render["reporting/excel.py<br/>コード方式・テンプレート方式の描画"]
    WB["完成したWorkbook"]
    UI -->|"固定IDで取得"| Registry
    Registry -->|"パターン"| Service
    UI -->|"選択済みRecord一覧"| Service
    Models --> UI
    Service -->|"コード方式"| Code
    Service --> API
    Code --> Spec
    Template --> Loader
    API --> Loader
    Loader --> Spec
    Loader --> Place
    Spec --> Project
    API --> Project
    Project --> Data
    Data --> Render
    Place --> Render
    Template -->|"読み込み済みWorkbookの書式"| Render
    Render --> WB
    WB -->|"呼び出し側がsave"| File["出力.xlsx"]
```

`reporting/models.py`がSpecとDataを定義します。パターンは1ブック全体に対応し、
複数シートを含められます。テンプレート方式の条件・列を登録一覧へ重複記載しません。

## 共通データ処理（flowchart TD）

```mermaid
flowchart TD
    Input["Record一覧・ReportSpec・モデル型"] --> Validate["参照フィールドと入力型を検証"]
    Validate --> Sort["各RecordのItemを一度だけソート<br/>元データは変更しない"]
    Sort --> Sheet["各シートを独立して処理"]
    Sheet --> Select["同一Item内でAND/ORを評価<br/>条件全体に1件でも一致したRecordを採用"]
    Select --> Common["採用したRecord間だけで共通値を比較<br/>印刷ヘッダー専用の項目も検証"]
    Common --> Equal{"共通値が一致？"}
    Equal -->|"不一致"| Error["ReportError"]
    Equal -->|"一致・対象0件"| Count["最大Item数から枠数を決定<br/>対象0件でも1枠残す"]
    Count --> Titles{"位置別名称が足りる？"}
    Titles -->|"不足"| Error
    Titles -->|"足りる"| Rows["Record列・全Itemの値を定義順に抽出"]
    Rows --> Result["全シートをまとめてWorkbookDataを返す"]
```

一致したItemだけを抜き出す処理ではありません。選んだRecordの全Itemを出力します。
ItemなしのRecordはANY条件に一致せず出力されません。Recordの行順は入力順です。
未採用Recordもソート対象となるため、そのソートエラーは出力前に検出されます。

## 印刷ヘッダーのデータ経路（flowchart LR）

```mermaid
flowchart LR
    Spec["PrintHeaderSpec<br/>指定タイトル・左右中央・書体"] --> Resolve["_set_print_header<br/>マーカーを一度だけ置換"]
    Data["HeaderData<br/>一致検証済みの共通値"] --> Resolve
    Resolve --> Header["Worksheet.oddHeader<br/>文字列とページ番号コード"]
    Header --> Excel["Excelの印刷処理<br/>ページ番号・総ページ数を確定"]
```

`show_table_headers=False`は共通項目のセル表示を止めます。列見出しは残り、
印刷用共通値の検証も実行します。テンプレートの固定文字や行配置は自動で削除しません。

## GUIからパターンを選ぶ流れ（sequenceDiagram）

```mermaid
sequenceDiagram
    autonumber
    actor User as 利用者
    participant UI as GUI（今後実装）
    participant Registry as report_patterns
    participant Service as report_service.py
    participant API as ReportGenerator
    UI->>Registry: list_patterns()
    Registry-->>UI: 固定ID・表示名・説明を持つ一覧
    User->>UI: データとパターンを選択
    User->>UI: 出力先を指定して実行
    UI->>Registry: get_pattern(選択ID)
    Registry-->>UI: ReportPattern
    UI->>Service: create_report(pattern, records)
    alt コード方式
        Service->>Service: pattern.spec_factory()
        Service->>API: code(records, 新しいspec)
    else テンプレート方式
        Service->>Service: テンプレートの存在確認
        Service->>API: template(records, template_path)
    end
    API-->>Service: Workbook
    Service-->>UI: Workbook
    UI->>UI: workbook.save(指定先)
    UI-->>User: 完了またはエラーを表示
```

GUIは表示名の文字列で分岐せず、選択項目に関連付けた固定IDで取得します。
データ取得・選択・保存先の指定・結果表示はGUI側の責務です。
生成時の例外は呼び出し側へ伝わるため、GUI側で捕捉して表示します。

## コード方式の内部呼び出し（sequenceDiagram）

```mermaid
sequenceDiagram
    autonumber
    participant Caller as 呼び出し側
    participant API as ReportGenerator
    participant Project as project.py
    participant Render as excel.py
    Caller->>API: code(records, spec)
    activate API
    API->>API: prepare(records, spec)
    API->>Project: project(records, spec, モデル型)
    Note over Project: 検証・ソート・シート別抽出・共通値検証
    Project-->>API: WorkbookData
    API->>Render: render_code(data)
    loop 各シート
        Render->>Render: _render_code_sheet(ws, sheet)
        Note over Render: セル共通項目・2段見出し・行・書式
        Render->>Render: _set_print_header(ws, sheet)
    end
    Render-->>API: 新規Workbook
    API-->>Caller: Workbook
    deactivate API
    Caller->>Caller: workbook.save(出力先)
```

## テンプレート方式の内部呼び出し（sequenceDiagram）

```mermaid
sequenceDiagram
    autonumber
    participant Caller as 呼び出し側
    participant API as ReportGenerator
    participant Openpyxl as openpyxl
    participant Loader as template.py
    participant Project as project.py
    participant Render as excel.py
    Caller->>API: template(records, path)
    API->>Openpyxl: load_workbook(path)
    Openpyxl-->>API: Workbook
    API->>Loader: load_template(wb)
    Note over Loader: 設定・マーカー・配置・結合の検証
    Loader-->>API: ReportSpec, placements
    API->>API: prepare(records, spec)
    API->>Project: project(records, spec, モデル型)
    Project-->>API: WorkbookData
    API->>Render: render_template(wb, data, placements)
    loop 各シート
        Render->>Render: _render_template_sheet(ws, sheet, place)
        Note over Render: 見本を横・下へ複製してから値を設定
        Render->>Render: _set_print_header(ws, sheet)
    end
    Render->>Render: 設定シートを除去
    Render-->>API: 更新したWorkbook
    API-->>Caller: Workbook
    Caller->>Caller: workbook.save(元テンプレートと別の出力先)
```

## 印刷ヘッダーの設定順（sequenceDiagram）

```mermaid
sequenceDiagram
    autonumber
    participant Render as シート描画処理
    participant Header as _set_print_header
    participant WS as Worksheet
    participant Caller as 呼び出し側
    participant Excel as Excelアプリ
    Render->>Header: ws, SheetData
    alt print_headerがNone
        Note over Header,WS: 既存ヘッダーを保持
    else print_headerが設定済み
        Header->>Header: 共通値とタイトルを文字列にする
        Header->>Header: ページ番号マーカーを&P・&Nへ変換
        Header->>WS: 左・中央・右と書体を設定
        Header->>WS: 先頭・偶数ページも共通設定にする
    end
    Header-->>Render: 処理完了
    Caller->>Caller: workbook.save(出力先)
    Caller->>Excel: 保存ファイルを開いて印刷プレビュー
    Excel->>Excel: 印刷設定に基づきページ数を計算
    Excel-->>Caller: 現在ページ・総ページ数を表示
```

## 変更箇所の目安

| 変更内容 | 変更箇所 |
|---|---|
| 業務モデル | `report_models.py` |
| パターンの追加・表示名・説明 | `report_patterns/registry.py` |
| コード方式の条件・列・ヘッダー | `report_patterns/inspection.py`・`voltage.py` |
| テンプレート方式の条件・列・ヘッダー・書式 | `templates/`内の.xlsx |
| GUIとの接点・モデルの組み合わせ | `report_service.py` |
| 共通のデータ変換 | `reporting/project.py` |
| 描画・複製 | `reporting/excel.py` |

出力ごとに変更したいタイトルなどが増えた場合は、パターンとは別に1回分の
オプションを渡す拡張を検討します。現段階では専用のオプションAPIは未実装です。
