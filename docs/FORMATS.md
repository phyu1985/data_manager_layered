# 各形式の使用方法と対応範囲

現構成向けにimportと資料リンクを更新。詳細な制約は[LIMITATIONS.md](LIMITATIONS.md)も参照。

## 形式と入口

| 形式 | 拡張子・入口 | 対応する値 |
| --- | --- | --- |
| JSON | ObjectRepository / .json | 単一モデル・dict |
| YAML | ObjectRepository / .yaml, .yml | 単一モデル・dict、既存文書・テンプレートの合成 |
| 独自テキストv1 | ObjectRepository / .txt | 単一モデル・dict |
| CSV | RowsRepository / .csv | 同じ型のモデル一覧・dict一覧 |
| JSONL | RowsRepository / .jsonl | 同じ型・混在モデルの一覧・dict一覧 |
| 独自バイナリ波形 | WaveformRepository / load・peek | WaveformObject・NumPy配列。読み取り専用 |

混在モデルの既定の形式はJSONLです。CSVへ渡すとエラーになります。
dictモードも、保存・読み込みの入口を増やさずmodel=dictで指定します。

## 共通の入力規則

- dictのキーは配列内の辞書も含め、全階層でstrを要求します。整数キーを勝手に文字列へ変えません。
- JSON / JSONL / 独自テキスト内のJSON値は、重複キーと有限値として保持できない数値をエラーにします。
- BaseModelは検証済みの入力として扱います。生成後の変更や検証を省略したモデルの再検証方針はLIMITATIONS.mdを参照してください。
- ユースケース用の呼び出しは[用途別サービスと実行例](../examples/README.md)を参照してください。

## YAML

```python
from pathlib import Path
from DataManager import ObjectRepository

repository = ObjectRepository(
    model=Settings,
    base_directory=Path("data"),
    template_directory=Path("templates"),
)
repository.save("settings.yaml", settings, template_name="base.yaml")
settings = repository.load("settings.yaml")
```

値はテンプレート→既存文書→モデル値の順に重ねます。
マッピングは再帰マージし、配列と単一値は全体を置き換えます。
モデルから出力されない既存キー・テンプレートのキーは残ります。
モデルの既定値やNoneも出力されるため、既存値より優先されます。

既存のコメントを優先し、既存にない箇所ではテンプレートのコメントを残します。
キー順と文字列の引用符も保持します。ただし、置き換える配列の要素単位のコメントを
照合して移植する機能はありません。任意のYAML書式を無条件に保持する保証ではありません。
独自タグの値や循環参照は通常のdictへ安全に復元できないため拒否します。
循環エイリアスは値に変換される前に検出し、Noneへ変化して見逃されることを防ぎます。
循環していない共有エイリアスは受け入れ、アンカー付きの真偽値も通常のboolへ戻します。

テンプレートは固定ディレクトリ内の相対名で指定します。
テンプレートと出力の同一パス、ディレクトリ外への指定はエラーです。
テンプレートを自身のロック中に読み終えてから、保存先のロックを取得します。
保存先の既存読取→マージ→原子的保存は、同じ排他範囲で行います。

設定を変える場合はYamlSerializer(dump_options=YamlDumpOptions(...))を登録します。
ruamelの編集用状態は操作ごとに作り、Serializerの並行使用で共有しません。

## CSV

```python
repository = RowsRepository(model=Measurement, base_directory=Path("data"))
repository.save("measurements.csv", measurements)
measurements = repository.load("measurements.csv")
```

入れ子のdictはdetails.countのような列名へ展開します。
キー自体に階層区切りがある場合、a列とa.b列が共存する場合はエラーにします。
配列・空の階層・任意オブジェクトをstrで黙って保存することはありません。
Record.itemsのような可変長配列はCSVの初期対応範囲外です。JSONL等を使ってください。

列は全行のキーの和集合から出現順で作ります。1行目にない後続行の値も保存します。
columnsを明示した場合、その列にない値を黙って捨てずエラーにします。
0件の型付き一覧は、固定モデルから可能な列を決定して見出しを出します。
空のdict一覧や列を決められないモデルでは、CSVDumpOptions(columns=(...))が必要です。

空文字は既定でNoneへ戻します。空文字を保持したい場合はempty_as_none=Falseを指定します。
すべてのセルが空でも正当なレコードとして残し、空の物理行だけを飛ばします。
余分・不足のセル、重複・空欄の列名、不正な引用符はエラーです。
dictモードのセルは基本的にstrまたはNoneであり、数値の型までの往復にはモデル検証を使います。

```python
from DataManager import CSVDumpOptions, CSVLoadOptions, CsvSerializer

serializer = CsvSerializer(
    dump_options=CSVDumpOptions(include_header=False, columns=("name", "count")),
    load_options=CSVLoadOptions(
        has_header=False, columns=("name", "count"), empty_as_none=False,
    ),
    encoding="utf-8-sig",
)
```

## 独自テキストv1

旧v0の構造を基に、値をJSONリテラルとして記録します。

```text
# v1
name:"001"
details.count:3
details.enabled:true
optional:null
items:[1,"a",null]
```

文字列の数字、空文字、None、真偽値、配列、空の辞書を区別できます。
モデルの値はPydanticでJSON向けに変換してから出力します。
CustomTextOptions(separator="/")の指定は、保存と読み込みの両方に適用します。
階層区切りを含むキー、コロン・改行を含むキー、重複や衝突はエラーです。

旧v0は未運用という前提に基づき、自動互換を設けていません。
# v0を読むと明示的にエラーになります。文字列化した旧データの型を推測して復元しません。

## 波形：内部仕様を共有しない接続

利用側の社内モジュールに、次の契約の関数を用意します。
ヘッダーの内部項目・位置の計算式をこのライブラリへ移す必要はありません。

```python
from typing import BinaryIO
from DataManager import WaveformHeader

# 社内側で実装する関数の契約:
# read_company_header(stream: BinaryIO) -> WaveformHeader
# 戻り値のvaluesには、必要な汎用項目を正規化して格納する。
# data_offsetは、復号後ストリームの先頭からの絶対バイト位置。
```

```python
from company_private import read_company_header
from DataManager import WaveformOptions, WaveformRepository

repository = WaveformRepository(
    base_directory=Path("data"),
    options=WaveformOptions(header_reader=read_company_header),
)
waveform = repository.load("wave.bin")
first_sample = repository.peek("wave.bin")
```

社内関数が返す汎用項目:

| 項目 | 意味 |
| --- | --- |
| channels | 順序付きチャネル番号一覧、またはカンマ区切り文字列 |
| channel_mask | channelsの代わりに使える正の整数ビットマスク |
| samples | サンプル数。省略時は本体長から決定 |
| endianness | little / big。省略時はlittle |
| signed | bool。省略時はTrue |

header_reader未指定では境界を推測せずエラーにします。
設定のendianness / signedが指定された場合はヘッダー値より優先します。
波形は各チャネルのshort型(x, y)で、配列の形は(samples, channels, 2)です。
チャネルの重複、サンプル幅の端数、指定samplesとの不一致は切り捨てずエラーにします。
samples=0が明示された空データはload可能ですが、peekではエラーです。

peekは本体の先頭1サンプルだけを読みます。ヘッダー解析と復号自体のコストは注入関数に依存します。
返す配列はコピーであり、操作終了後に編集できます。

暗号化は外部のdecryptor: Callable[[BinaryIO], BinaryIO]を指定します。
decrypt="auto"の既定では.shnに復号を要求し、その他の拡張子はそのまま読みます。
復号後のストリームはseek可能で、操作ごとに新しく用意してください。
返された別ストリームはライブラリ側が操作終了時にcloseします。
復号後ストリームをヘッダー解析へ渡すため、境界の位置は復号後のバイト列が基準です。

実ファイル・実暗号方式・社内ヘッダーとの結合は、社内側の関数を接続して確認する必要があります。
このリポジトリのテストとexamples/formats.pyでは、社内仕様を含まない合成形式を使っています。
