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
