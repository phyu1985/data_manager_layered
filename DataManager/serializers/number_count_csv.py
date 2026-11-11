""" NUMBER/COUNTの二表と任意の末尾Flagを持つ、V0 CSVの専用処理。
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
import csv
from io import StringIO
from typing import Any

from DataManager.documents import RowsDocument
from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue
from DataManager.serializers.csv_headers import dump_header_text, split_header
from DataManager.serializers.csv_options import CsvHeaderField, CsvHeaderOptions

_HEADER = CsvHeaderOptions(
    fields=(
        CsvHeaderField.whitespace("version"),
        CsvHeaderField.separated("number"), CsvHeaderField.separated("count"),
    ),
    comment_prefixes=("#",),
)
_NUMBER_COLUMNS = ("NUMBERINDEX", "NUMBERID", "NAME")
_COUNT_COLUMNS = ("index", "order", "value")

# 種類・表名・実データの列・ファイルの見出しをまとめる。COUNTのindexは見出しにない。
_TABLES = (
    ("number", "# NUMBER TABLE", _NUMBER_COLUMNS, _NUMBER_COLUMNS),
    ("count", "# COUNT TABLE", _COUNT_COLUMNS, _COUNT_COLUMNS[1:]),
)


class NumberCountCsvSerializer:
    """ V0の配置を解釈し、表の種類付きdict一覧と共通メタへ変換する。

    列名の版変換や現在モデルの生成は行わない。ファイル操作はRowsRepositoryへ任せる。
    保存はメタ付き文書を使い、末尾Flagだけを先頭メタと別の位置へ戻す。
    """

    @property
    def encoding(self) -> str:
        return "utf-8"

    def validate_model_configuration(self, model_binding: ModelBinding[ModelValue]):
        """ 版変換前のdict用Repositoryへ接続する。
        """
        if model_binding.data_mode != "dict":
            raise ConfigurationError("NumberCountCsvSerializerはV0のdict用です。モデル復元にはVersionedRowsRepositoryを組み合わせてください")

    @staticmethod
    def _integer(value: object, label: str) -> int:
        """ 整数表記だけを受け入れ、boolや小数を黙って整数へ変えない。
        """
        if type(value) is int:
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.lstrip("+-").isdecimal():
                try:
                    return int(text)
                except ValueError:
                    pass
        raise SerializationError(f"{label}は整数が必要です")

    def _prepare_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """ V0の制御項目を確認し、NoneのFlagだけを省略したコピーを返す。
        """
        required = {"version", "number", "count"}
        missing = required - metadata.keys()
        unexpected = metadata.keys() - required - {"Flag"}
        if missing or unexpected:
            raise SerializationError(f"V0のメタ項目が一致しません。不足={sorted(missing)}、余剰={sorted(unexpected)}")

        values = {name: self._integer(metadata[name], name) for name in ("version", "number", "count")}
        if values["version"] != 0:
            raise SerializationError("このCSVの保存版はV0です。VersionedRowsRepository.for_version(0)を指定してください")
        if values["number"] < 0 or values["count"] < 0:
            raise SerializationError("number/countは0以上が必要です")

        result: dict[str, Any] = dict(values)
        if metadata.get("Flag") is not None:
            result["Flag"] = self._integer(metadata["Flag"], "Flag")
        return result

    @staticmethod
    def _records(text: str) -> Iterator[list[str]]:
        """ CSVの論理レコードを読み、引用符の外の空行だけを読み飛ばす。
        """
        stream = StringIO(text, newline="")
        reader = csv.reader(stream, skipinitialspace=True, strict=True)
        try:
            while True:
                start = stream.tell()
                record = next(reader, None)
                if record is None:
                    return
                if not text[start:stream.tell()].strip():
                    continue
                yield record
        except csv.Error as error:
            raise SerializationError(f"二表CSVのレコードが不正です: {error}") from error

    def _row_values(
        self, values: Sequence[object], columns: tuple[str, ...], location: str,
    ) -> dict[str, Any]:
        """ V0のNAMEは文字列、それ以外は整数列として復元する。
        """
        if len(values) != len(columns):
            raise SerializationError(f"{location}: 値は{len(columns)}項目が必要です")
        data: dict[str, Any] = {}
        for name, value in zip(columns, values, strict=True):
            if name == "NAME":
                if not isinstance(value, str):
                    raise SerializationError(f"{location}.NAMEは文字列が必要です")
                data[name] = value
            else:
                data[name] = self._integer(value, f"{location}.{name}")
        return data

    def _read_table(
        self, records: Iterator[list[str]], *, tag: str, title: str,
        columns: tuple[str, ...], header: tuple[str, ...], count: int,
    ) -> list[dict[str, Any]]:
        """ 表名・列名・指定件数の順に読み、末尾メタをデータへ取り込まない。
        """
        for record in records:
            if len(record) == 1 and " ".join(record[0].split()) == title:
                break
            if not record[0].lstrip().startswith("#"):
                raise SerializationError(f"表の開始がありません: {title}")
        else:
            raise SerializationError(f"表の開始がありません: {title}")

        record = next(records, None)
        if record is None or not record[0].lstrip().startswith("#"):
            raise SerializationError(f"{title}の#付き列名がありません")
        actual_header = (record[0].lstrip()[1:].strip(), *(value.strip() for value in record[1:]))
        if actual_header != header:
            raise SerializationError(f"{title}の列名が一致しません: {actual_header}")

        rows: list[dict[str, Any]] = []
        for i in range(count):
            record = next(records, None)
            if record is None:
                raise SerializationError(f"{title}のデータが不足しています。指定件数={count}")
            data = self._row_values(record, columns, f"{title}の{i + 1}件目")
            rows.append({"type": tag, **data})
        return rows

    def loads_document(
        self, serialized_text: str, model_binding: ModelBinding[ModelValue],
    ) -> RowsDocument[dict[str, Any], ModelValue]:
        """ 先頭メタ→NUMBER→COUNT→任意のFlagという配置順で読む。
        """
        self.validate_model_configuration(model_binding)
        metadata, body = split_header(serialized_text, _HEADER, ",")
        metadata = self._prepare_metadata(metadata)
        records = self._records(body)

        # 表の種類はマーカーから確定する。COUNTのindexは先頭の実データを読む。
        rows: list[dict[str, Any]] = []
        for tag, title, columns, header in _TABLES:
            rows.extend(self._read_table(
                records, tag=tag, title=title, columns=columns, header=header, count=metadata[tag],
            ))

        # 本文を指定件数読んだ後だけFlagを解釈する。引用符内のFlagや改行には触れない。
        footer = next(records, None)
        if footer is not None:
            key, separator, value = footer[0].partition(":")
            if len(footer) != 1 or key.strip() != "Flag" or not separator:
                raise SerializationError("COUNT TABLEの後にはFlag: 整数だけを記載できます")
            metadata["Flag"] = self._integer(value, "Flag")
            if next(records, None) is not None:
                raise SerializationError("Flagの後に余分なデータがあります")
        return RowsDocument(metadata=metadata, rows=[model_binding.restore_value(row) for row in rows])

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> list[ModelValue]:
        """ 本文だけを利用する場合も、メタと件数の確認は行う。
        """
        return self.loads_document(serialized_text, model_binding).rows

    def dumps_document(
        self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue], *, metadata: dict[str, Any],
    ) -> str:
        """ 行を表ごとに戻し、先頭メタと任意の末尾Flagを一つの文書へ生成する。
        """
        self.validate_model_configuration(model_binding)
        metadata = self._prepare_metadata(metadata)
        grouped: dict[str, list[dict[str, Any]]] = {tag: [] for tag, _, _, _ in _TABLES}
        for i, row in enumerate(rows, start=1):
            data = model_binding.to_dict(row, by_alias=False)
            tag = data.get("type")
            if not isinstance(tag, str) or tag not in grouped:
                raise SerializationError(f"V0の{i}件目にnumber/countのtypeが必要です")
            grouped[tag].append(data)

        # 件数を黙って修正しない。編集後は呼出側で保存用メタを更新する。
        output = StringIO(newline="")
        output.write(dump_header_text({field.name: metadata[field.name] for field in _HEADER.fields}, _HEADER, ","))
        writer = csv.writer(output, lineterminator="\n", quoting=csv.QUOTE_NONNUMERIC)
        for tag, title, columns, header in _TABLES:
            table = grouped[tag]
            if len(table) != metadata[tag]:
                raise SerializationError(f"{tag}={metadata[tag]}と{title}の実件数{len(table)}が一致しません")
            output.write("\n" + title + "\n# " + ", ".join(header) + "\n")
            for i, data in enumerate(table, start=1):
                if set(data) != {"type", *columns}:
                    raise SerializationError(f"{title}の{i}件目の保存項目がV0の列と一致しません。downcastを確認してください")
                values = self._row_values([data[name] for name in columns], columns, f"{title}の{i}件目")
                # 文字列を引用し、意図的な先頭空白をskipinitialspaceで失わないようにする。
                writer.writerow([values[name] for name in columns])

        if "Flag" in metadata:
            output.write(f"Flag: {metadata['Flag']}\n")
        return output.getvalue()

    def dumps(self, rows: Sequence[ModelValue], model_binding: ModelBinding[ModelValue]) -> str:
        """ この形式は件数メタが必要なため、文書保存を要求する。
        """
        raise ConfigurationError("number/countを含むメタが必要です。save_documentを使用してください")
