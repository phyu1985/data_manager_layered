# 実行例一覧

すべてプロジェクトのルートで実行します。Pythonの前に`.venv/Scripts/`等を付けるか、仮想環境を有効化してください。

| コマンド | 見ることができる機能 | 出力先 |
|---|---|---|
| `python main.py outputs/demo` | 生データ→加工→保存→解析→再解析→CSV帳票 | 指定先の3データファイル |
| `python -m View.end_to_end outputs/demo-jsonl --report-format jsonl` | 同じ処理からJSONL帳票 | 指定先 |
| `python main.py outputs/demo-xlsx --report-format xlsx` | 同じ処理からExcel帳票 | 指定先 |
| `python -m examples.formats` | JSON/YAML/text/CSV/混在JSONL/dict/合成波形 | outputs/formats |
| `python -m examples.application_services` | 保存先とモデルを事前構成したservicesの使い方 | outputs/services |
| `python -m examples.workflow outputs/compat --excel` | 旧版読取・項目保持/廃止・旧版別名保存・外部集約・3種帳票 | 指定先 |
| `python -m examples.excel_reports` | Excelコード方式とテンプレート方式の比較 | outputs/excel |

全工程と互換保存の例は既存出力先を上書きしません。別名の出力先を指定してください。形式別・services・Excel単体例は固定された合成出力先を再生成する実験用です。実データをこの場所へ置かないでください。

examplesでは学習のため、モデル定義・組立て・printを近くに置いています。業務へ採用する場合はDomain/DataManager/UseCase/Viewの対応する責務へ移してください。実際の4レイヤ構成はmain.pyから始める例です。

これ以前に作った例もreference/previous_projectsに残しています。古い例には旧importや元々の不整合があるため、この一覧の現構成向け例から使ってください。テンプレート、既存の合成出力ファイルも参照保管しています。
