# DataManager・解析・Excel帳票の統合サンプル

Python 3.12以上 / Pydantic v2。生データの読取から加工、解析、再解析、互換保存、帳票出力までを、4つのトップレイヤで扱うプロジェクトです。

自作モジュールをインストールする必要はありません。`src`フォルダ、`pip install -e .`、`PYTHONPATH`の指定は使いません。外部ライブラリだけをrequirementsからインストールし、このフォルダをカレントディレクトリにして実行します。

```text
data_manager_layered/
├── main.py              # Viewを起動する入口
├── View/                # 引数・表示。UseCaseを呼ぶ
├── UseCase/             # 加工→保存→解析→再解析→帳票という手順
├── Domain/              # 処理用モデル、計算、帳票明細の組立て
├── DataManager/          # Repository、Serializer、版変換、保存先、Excelエンジン
├── examples/             # 形式別・サービス・旧版保存・Excel単体の実行例
├── sample_outputs/       # 各実行例の出力見本（Gitへ含める）
├── sample_data/          # 機密情報を含まない合成CSV
├── docs/                 # 現構成の設計・流れ・使い方・制約
├── tests/                # 動作・境界・排他・Excelの回帰テスト
├── typecheck/            # 型推論と誤入力検出の確認用コード
├── tools/                # 検証用スクリプト
└── reference/            # 元プロジェクトと以前の説明・図・実行例の保管
```

## 最初に動かす（PowerShell）

このREADMEがあるフォルダで実行します。仮想環境を有効化しない場合も、以下のようにPythonの場所を直接指定できます。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py outputs/first-run
.\.venv\Scripts\python.exe main.py outputs/excel-run --report-format xlsx
```

`requirements-dev.txt`はExcelと検証ツールを含みます。実行だけなら`requirements.txt`、Excelは`requirements-excel.txt`、DataFrameは`requirements-pandas.txt`を使います。

全工程の例は、未作成の出力先を指定します。同じ出力先を指定すると、既存データ保護のためエラーになります。`outputs/first-run`には設定YAML・測定JSONL・選択した帳票の3ファイルができます。保存領域のstorage.jsonとapplication_controlが作られます。解析フォルダへ個別の.lockを並べず、ガードを管理領域へ集約します。

## 普通のimportで呼ぶ

```python
from UseCase.analysis import AnalysisWorkspace
from Domain.models import AnalysisPresets
from DataManager import ObjectRepository, RowsRepository
```

入口から動かすなら`python main.py 出力先`または`python -m View.end_to_end 出力先`です。`python View/end_to_end.py`のようなレイヤ内ファイルの直接実行は対象外です。`View`など大文字小文字を含めて同じ名前でimportしてください。

## 読む順番

まず[ファイル窓口と役割の整理](docs/FILE_INTERFACES.md)で、FileService / Repository / AnalysisWorkspaceの使い分けを確認できます。

1. [何を狙った構成か・依存方向・クラス図](docs/ARCHITECTURE.md)
2. [加工から再解析・帳票までの手順とコードの対応](docs/WORKFLOW.md)
3. [ファイル一覧・旧構成からの移動先](docs/FILE_LAYOUT.md)
4. [すべての実行例と出力の見方](examples/README.md)
5. [版互換・独自形式を追加する場所](docs/EXTENDING.md)
6. [検証結果と、実運用までに残っていること](VALIDATION.md)
7. [拡張形式・Rows版変換・DataFrameの使い方](docs/EXTENSION_GUIDE.md)
8. [保存領域の初期化・共有編集権・強制引継ぎ](docs/SHARED_EDITING.md)
9. [CSV・JSONL共通のメタ情報API](docs/METADATA.md)
10. [各形式の詳しい仕様・オプション・波形の接続](docs/FORMATS.md)
11. [元の説明資料・構成図・サンプルの一覧](reference/README.md)

## 検証

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\pyright.exe
.\.venv\Scripts\python.exe tools/check_negative_types.py
.\.venv\Scripts\python.exe tools/check_release.py
```

GitHub Actionsにも同じ手順と全実行例のスモークテストを設定しています。`reference`は参照保管用で、現在のテスト・型チェック対象には含みません。

実業務のモデル・独自形式・機密の波形境界規則は収録していません。サンプル計算を実際の加工・解析へ置き換える場所はDomainです。実運用上の制約を[こちら](docs/LIMITATIONS.md)に明記しています。公開ライセンスは未設定です。GitHubへ公開する際の利用条件は所有者が決定してください。

共有の解析データを使う場合、保守担当者が保存領域をStorage.initializeで一度だけ初期化してください。AnalysisWorkspaceは初期化済み領域を必須にします。アプリが起動ごとに別の管理領域を作る方式ではありません。強制編集の例は`python -m examples.shared_editing outputs/shared`です。
