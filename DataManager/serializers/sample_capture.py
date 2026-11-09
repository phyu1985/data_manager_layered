""" 未提示の社内仕様の代わりに用意した、架空の位置依存テキストと2表CSV。

    実ファイル対応を意味しない。形式固有の処理をどこに置くかを示す例であり、
    本番ではこのモジュール相当の読取規則だけを置き換える。
"""
from __future__ import annotations

from collections.abc import Sequence
import csv
from io import StringIO
import shlex
from typing import Any, Literal

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv import CsvOptions, CsvSerializer

RawDocument = RowsDocument[dict[str, Any], dict[str, Any]]


class PositionalCaptureSerializer:
    """ CAPTURE、版/機器/件数、空白区切りの時刻/値を読む架空の旧形式。

    読取専用。標準KVやJSONへの出力は別のObjectRepositoryへ渡す。
    """

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return False

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ 位置でキーを付けるだけに留め、旧項目の改名や単位変更はキャストへ渡す。
        """
        lines = [line for line in serialized_text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if len(lines) < 2 or lines[0] != "CAPTURE":
            raise SerializationError("架空CAPTURE形式の開始行がありません")

        # 先頭2行で版・機器・件数を確定し、それ以降の位置を旧キーへ対応付ける。
        header = shlex.split(lines[1])
        if len(header) != 3:
            raise SerializationError("CAPTUREヘッダは版・機器・件数の3値です")
        try:
            version, number = int(header[0]), int(header[2])
        except ValueError as error:
            raise SerializationError("版と件数は整数です") from error
        if number < 0 or len(lines[2:]) != number:
            raise SerializationError("CAPTUREの収録件数が一致しません")

        rows: list[dict[str, str]] = []
        for line in lines[2:]:
            cells = shlex.split(line)
            if len(cells) != 2:
                raise SerializationError("CAPTUREのデータは2値です")
            rows.append({"tick": cells[0], "reading": cells[1]})

        return model_binding.restore_value({"version": version, "device": header[1], "rows": rows})

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        raise ConfigurationError("架空CAPTURE入力は読取専用です。KV/JSONの出力先を別途指定してください")


class CaptureCsvFormat:
    """ 先頭ヘッダで件数・後半の列数を決定する、架空の2テーブル文法。

    全体の解析は一つに集約し、前半用・後半用Repositoryがこの処理へ委譲する。
    ファイルを開かず、Repositoryが一度取得した文字列を解析する。
    """

    def decode(self, text: str) -> tuple[RawDocument, RawDocument]:
        """ 件数で位置を求め、マーカーでも照合してから後半へ進む。
        """
        try:
            records = list(csv.reader(StringIO(text, newline=""), strict=True))
        except csv.Error as error:
            raise SerializationError(f"CAPTURE CSVのセルが不正です: {error}") from error
        index = 0

        def metadata_until(marker: str) -> dict[str, Any]:
            nonlocal index
            metadata: dict[str, Any] = {}
            while index < len(records) and records[index] != [marker]:
                row = records[index]
                index += 1
                if len(row) != 2 or not row[0] or row[0] in metadata:
                    raise SerializationError("CAPTURE CSVのヘッダが不正です")
                metadata[row[0]] = row[1]
            if index == len(records):
                raise SerializationError(f"マーカーがありません: {marker}")
            index += 1
            return metadata

        # 前半のヘッダが、最初の表の件数と後半のチャネル構成を決める。
        first_meta = metadata_until("[data]")
        try:
            number = int(first_meta["number"])
            channel_count = int(first_meta["channel_count"])
        except (KeyError, ValueError, TypeError) as error:
            raise SerializationError("先頭ヘッダにnumberとchannel_countの整数が必要です") from error
        if number < 0 or channel_count <= 0:
            raise SerializationError("件数は0以上、チャンネル数は1以上です")

        first_cells = records[index:index + number + 1]
        index += number + 1
        if index >= len(records) or records[index] != ["[header2]"]:
            raise SerializationError("前半の件数と[header2]の位置が一致しません")

        # 件数で求めた位置をマーカーでも確認し、後半のヘッダへ進む。
        index += 1
        second_meta = metadata_until("[channels]")
        try:
            second_number = int(second_meta["number"])
        except (KeyError, TypeError, ValueError) as error:
            raise SerializationError("後半ヘッダにnumberの整数が必要です") from error
        if second_number < 0 or len(records[index:]) != second_number:
            raise SerializationError("後半の収録件数が一致しません")

        # 後半には列名がないため、先頭ヘッダのチャネル数から復元先を作る。
        channels = tuple(f"channel_{i + 1}" for i in range(channel_count))
        second_meta = {**second_meta, "channel_count": channel_count}
        binding = ModelBinding[dict[str, Any]](dict)
        first = CsvSerializer().loads(self._text(first_cells), binding)
        second = CsvSerializer(options=CsvOptions(header=False, columns=channels)).loads(self._text(records[index:]), binding)
        return RowsDocument(first_meta, first), RowsDocument(second_meta, second)

    @staticmethod
    def _text(records: Sequence[Sequence[Any]]) -> str:
        output = StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerows(records)
        return output.getvalue()

    def encode(self, first: RawDocument, second: RawDocument) -> str:
        """ 全体の新規出力用。部分更新は行わず、数と列構成を再生成して照合する。
        """
        try:
            count = int(first.metadata["channel_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise SerializationError("channel_countが必要です") from error
        if count <= 0:
            raise SerializationError("channel_countは1以上です")
        channels = tuple(f"channel_{i + 1}" for i in range(count))
        binding = ModelBinding[dict[str, Any]](dict)
        first_text = CsvSerializer(options=CsvOptions(columns=("time", "value"))).dumps(first.rows, binding)
        second_text = CsvSerializer(options=CsvOptions(header=False, columns=channels)).dumps(second.rows, binding)
        first_meta = {**first.metadata, "number": len(first.rows)}
        second_meta = {key: value for key, value in second.metadata.items() if key != "channel_count"}
        second_meta["number"] = len(second.rows)
        text = (
            self._text([[key, value] for key, value in first_meta.items()]) + "[data]\n" + first_text
            + "[header2]\n" + self._text([[key, value] for key, value in second_meta.items()])
            + "[channels]\n" + second_text
        )
        # 再読できる構造かを確認してから返し、件数とマーカーのずれを保存しない。
        self.decode(text)
        return text


class CaptureSectionSerializer:
    """ 共通の文法から指定した表だけを返す。キャッシュや他Repositoryの状態に依存しない。
    """

    def __init__(self, section: Literal["first", "second"], *, format_reader: CaptureCsvFormat | None = None):
        if section not in {"first", "second"}:
            raise ConfigurationError("sectionはfirst / secondです")
        self._section = section
        self._format = format_reader or CaptureCsvFormat()

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        if model_binding.data_mode == "mixed":
            raise ConfigurationError("CAPTURE CSVの表は同じ行モデルに揃えてください")

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        self.validate_model_configuration(model_binding)
        sections = self._format.decode(serialized_text)
        selected = sections[0 if self._section == "first" else 1]
        return RowsDocument(selected.metadata, [model_binding.restore_value(row) for row in selected.rows])

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        return self.loads_document(serialized_text, model_binding).rows

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        raise ConfigurationError("一方の表だけでは保存できません。CaptureCsvFileSerializerで全体を保存してください")

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        return self.dumps(rows, model_binding)


class CaptureCsvFileSerializer:
    """ 二つの表をそろえたオブジェクトを、既存ObjectRepositoryで新規出力する。
    """

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return False

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        first, second = CaptureCsvFormat().decode(serialized_text)
        return model_binding.restore_value({
            "first": {"metadata": first.metadata, "rows": first.rows},
            "second": {"metadata": second.metadata, "rows": second.rows},
        })

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        if existing_text is not None or template_text is not None:
            raise ConfigurationError("CAPTURE CSVの部分マージは未対応です")
        data = model_binding.to_dict(value, by_alias=False)
        try:
            first, second = data["first"], data["second"]
            return CaptureCsvFormat().encode(RowsDocument(first["metadata"], first["rows"]),
                                             RowsDocument(second["metadata"], second["rows"]))
        except (KeyError, TypeError) as error:
            raise SerializationError("first/secondそれぞれにmetadataとrowsが必要です") from error
