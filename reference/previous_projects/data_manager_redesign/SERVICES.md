# ユースケースから使うservicesモジュール

> v0.3.0追記：本書は検討経緯を含みます。用途別Presetsで必要項目を明示し、Settingsの子への一律置換はしません。現在の実装・責務・使い方は[WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)を先に参照してください。辞書間の隣接版変換とObject用サービスは実装済み、実業務の変換やINI対応等は未実装です。

2026-10-31 / v0.2.1

## 役割

ユースケースで繰り返すモデル・ファイル名・テンプレートの指定を、アプリ側のservicesモジュールへ集約します。
ライブラリのサービスは、その組み合わせを固定する小さな窓口です。
変換・排他・原子的保存・JSONLの型判別は既存Repository / Serializerへ任せます。

```text
ユースケース
    ↓ services.settings.load() / services.events.append(...)
ファイルと方針を固定したService
    ↓
Repository → Serializer → モデルの復元
```

サービスの組み立てではファイルを読み書きしません。必要な操作を呼んだときにだけI/Oが発生します。
既存のRepositoryを直接使う方法も残っています。

## 単一モデル

```python
from pathlib import Path
from data_manager import ObjectFileService, ObjectRepository

settings_service = ObjectFileService(
    repository=ObjectRepository(
        model=ApplicationSettings,
        base_directory=Path("data"),
        template_directory=Path("templates"),
    ),
    path="config/settings.yaml",
    template_name="settings.yaml",
)

settings = settings_service.load()  # ApplicationSettings
settings_service.save(ApplicationSettings(project_name="inspection"))
```

テンプレート指定は任意です。ファイルの形式は、固定したpathの拡張子からRepositoryが決めます。
dictもObjectRepository[dict[str, Any]](model=dict, ...)と組み合わせて使えます。

## 一覧と混在JSONL

```python
from data_manager import RowsFileService, RowsRepository

events_service = RowsFileService[MeasurementEvent | AuditEvent](
    repository=RowsRepository[MeasurementEvent | AuditEvent](
        model=(MeasurementEvent, AuditEvent),
        base_directory=Path("data"),
    ),
    path="logs/events.jsonl",
)

events_service.save([])
events_service.append([MeasurementEvent(message="finished")])
events = events_service.load()  # list[MeasurementEvent | AuditEvent]
```

CSVもRowsFileServiceで全件保存・読み込みできます。appendはJSONL専用で、CSVを全件読み直して代用しません。
tagの設定やCSVの空欄方針などは、Repositoryへ登録するSerializerに一度だけ設定します。
サービスが専用optionsを複製したり、未定義の属性を補完したりすることはありません。

## 波形

```python
from data_manager import WaveformFileService, WaveformOptions, WaveformRepository

waveform_service = WaveformFileService(
    repository=WaveformRepository(
        base_directory=Path("data"),
        options=WaveformOptions(header_reader=read_company_header),
    ),
    path="wave.bin",
)

waveform = waveform_service.load()
first_sample = waveform_service.peek()
```

読み取り専用なのでsaveはありません。社内の境界規則はread_company_headerの実装内に残せます。

## アプリ側で用途別に公開する

[examples/application_services.py](examples/application_services.py)に、設定・測定CSV・混在ログをまとめる実行例があります。

```python
services = create_project_services(Path("data"))

# ユースケースには、保存先・拡張子・Serializer設定を繰り返し書かない。
settings = services.settings.load()
measurements = services.measurements.load()
services.events.append([AuditEvent(operation="exported")])
```

ProjectServicesの公開フィールドは、利用側が用途を選ぶための窓口です。
frozen dataclassにより、窓口の組み合わせ自体は後から差し替えられないようにしています。

既存アプリではこの例のモデルを使う必要はありません。業務モデルとファイル名を自分のservicesモジュールで組み立ててください。
必要ならload_settingsなどの業務名を持つ関数で、この窓口を呼び出す形にできます。

## 責務と保証

- エラーを握りつぶして空値や既定モデルへ置き換えません。Repository / Pydanticの例外を引き継ぎます。
- 欠損ファイルを初期作成するか、どの業務値を初期値にするかはユースケースの判断です。
- 複数ファイルを順番に保存しても、全体を1つのトランザクションにする保証はありません。
- サービスの追加で、直接JSONL追記の障害時保証が強くなることはありません。
- 大きなDIコンテナ、グローバルRegistry、設定の自動探索、UoWは導入していません。
- メタなし外部JSONLを読む専用Serializerは、現状では読み込み用途に分けて構成してください。

今後の仕様判断が必要な点は[REVIEW_REPORT.md](REVIEW_REPORT.md)にまとめています。
