# 実行例一覧

すべてプロジェクトのルートで実行します。Pythonの前に`.venv/Scripts/`等を付けるか、仮想環境を有効化してください。

| コマンド | 見ることができる機能 | 出力先 |
|---|---|---|
| `python main.py outputs/demo` | 生データ→加工→保存→解析→再解析→CSV帳票 | 指定先の3データファイル |
| `python -m View.end_to_end outputs/demo-jsonl --report-format jsonl` | 同じ処理からJSONL帳票 | 指定先 |
| `python main.py outputs/demo-xlsx --report-format xlsx` | 同じ処理からExcel帳票 | 指定先 |
| `python -m examples.extended_formats outputs/extended --pandas` | キーなしメタ・列名置換・KV・複数行・2表・位置依存入力・版変換・DataFrame | 指定先 |
| `python -m examples.shared_editing outputs/shared` | 共有管理領域・通常編集・強制引継ぎ・失効後保存拒否 | 指定先 |
| `python -m examples.versioned_files outputs/versioned-files` | YAMLの版別テンプレート・Rowsのmetaキャスト・属性8行 | 指定先 |
| `python -m examples.metadata` | CSVの空行・マーカー・固定件数とJSONLで共通のメタ入出力 | outputs/metadata |
| `python -m examples.formats` | JSON/YAML/text/CSV/混在JSONL/dict/合成波形 | outputs/formats |
| `python -m examples.application_services outputs/services` | 保存先とモデルを事前構成したservicesの使い方 | outputs/services |
| `python -m examples.workflow outputs/compat --excel` | 旧版読取・項目保持/廃止・旧版別名保存・外部集約・3種帳票 | 指定先 |
| `python -m examples.excel_reports` | Excelコード方式とテンプレート方式の比較 | outputs/excel |

全工程と互換保存の例は既存出力先を上書きしません。別名の出力先を指定してください。services例も未作成の出力先を指定します。形式別・Excel単体例は合成出力先を使う実験用です。実データをこの場所へ置かないでください。

examplesでは学習のため、モデル定義・組立て・printを近くに置いています。業務へ採用する場合はDomain/DataManager/UseCase/Viewの対応する責務へ移してください。実際の4レイヤ構成はmain.pyから始める例です。

これ以前に作った例もreference/previous_projectsに残しています。古い例には旧importや元々の不整合があるため、この一覧の現構成向け例から使ってください。テンプレート、既存の合成出力ファイルも参照保管しています。

追加例の入力はsample_data/extendedの人工データです。extended_formatsは--pandasを省けば基本依存だけで動きます。共有編集例はローカルの動作確認であり、SMBの実機検証を代替しません。

命名と共通I/Fは[FILE_INTERFACES.md](../docs/FILE_INTERFACES.md)を参照してください。例のProjectFilesは用途別の構成をまとめた値であり、モデルごとのServiceクラスを要求するものではありません。


CSV設定の全項目・条件とa〜gの例は[CSV設定ガイド](../docs/CSV_OPTIONS.md)を参照してください。

CSVのa〜gはcsv_layouts.pyのsample_a〜sample_gを参照してください。各関数に設定と入出力をまとめ、`python -m examples.csv_layouts outputs/csv-g --pattern g`のように単独実行もできます。


AA・AAAの二段形式と末尾空セルは[二段CSVの使い方](../docs/TWO_TABLE_CSV.md)を参照してください。


検証の担当と設定APIの整理は[処理と検証の整理](../docs/VALIDATION_FLOW.md)を参照してください。項目宣言型CSVと版変換は`python -m examples.versioned_csv outputs/versioned-csv`で実行できます。


JSONL・KV・BlockRowsの設定整理と移行方法は[各形式の設定](../docs/FORMAT_OPTIONS.md)を参照してください。

## コメント付きCSV

`python -m examples.csv_comments`でi〜i5（iii_1を含む）を個別の関数から読み込みます。設定の違いと自由文からのメタ抽出は[説明](../docs/CSV_COMMENTS.md)を参照してください。

V0 BlockRowsとV1 JSONL、版ごとのメタ名・版キー、単一/混在モデルの自動登録は[版付きRowsの構成](../docs/VERSIONED_ROWS.md)を参照してください。実行例はexamples/versioned_block_rows.pyです。

config 0→Config.version→V1 JSONL→V0別名保存に絞った実行例は[版キー名のサンプル](../docs/VERSION_KEY_NAMES.md)を参照してください。コードはexamples/version_key_names.pyです。

YAMLのルートlist、メタ付き一覧、V2/V3だけの版変換は[YAML Rowsの使い方](../docs/YAML_ROWS.md)を参照してください。実行例はexamples/yaml_rows.pyです。

j.csvのNUMBER/COUNT二表と末尾Flagを扱い、V1の混在JSONLへ変換する例は[専用CSVと版変換](../docs/NUMBER_COUNT_CSV.md)を参照してください。
