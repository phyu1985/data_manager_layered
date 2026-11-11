""" CSV文書の先頭をmetaと本文へ分け、表の変換からヘッダの書式を切り離す。
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
import json
from typing import Any
from uuid import UUID

from DataManager.errors import SerializationError
from DataManager.serializers.csv_options import CsvHeaderField, CsvHeaderOptions, CsvKeyValueHeaderOptions
from DataManager.serializers.text_header import dump_header, parse_header_line

HeaderOptions = CsvHeaderOptions | CsvKeyValueHeaderOptions


def _add_values(metadata: dict[str, Any], values: dict[str, str], *, empty_as_none: bool):
    """ 重複を上書きせず拒否し、空値の扱いをどのヘッダでも揃える。
    """
    if metadata.keys() & values.keys():
        raise SerializationError("CSVメタのキーが重複しています")
    metadata.update({key: None if value == "" and empty_as_none else value for key, value in values.items()})


def _field_value(text: str, field: CsvHeaderField) -> str:
    """ 項目のラベルと区切りを外し、値だけの項目はCSVセルのまま保持する。
    """
    if field.separator is None:
        return text

    text = text.strip()
    if not text.startswith(field.name):
        raise SerializationError(f"ヘッダ{field.name}: 項目名が一致しません")
    value = text[len(field.name):]
    if field.separator == " ":
        if not value or not value[0].isspace():
            raise SerializationError(f"ヘッダ{field.name}: 空白区切りがありません")
    elif field.separator:
        value = value.lstrip()
        if not value.startswith(field.separator):
            raise SerializationError(f"ヘッダ{field.name}: 区切りが一致しません")
        value = value[len(field.separator):]

    # 名前付き値の前後空白は文法として除き、有意な空白は引用文字列から復元する。
    value = value.strip()
    if not value.startswith('"'):
        return value
    try:
        decoded: object = json.loads(value)
    except ValueError as error:
        raise SerializationError(f"ヘッダ{field.name}: 引用文字列が不正です") from error
    if not isinstance(decoded, str):
        raise SerializationError("ヘッダの引用値は文字列が必要です")
    return decoded


def _declared_values(text: str, options: CsvHeaderOptions, delimiter: str) -> tuple[dict[str, Any], str]:
    """ 先頭説明・項目一覧・本文の順に進み、記載順の規則を一か所で読めるようにする。
    """
    stream = StringIO(text, newline="")
    reader = csv.reader(stream, delimiter=delimiter, skipinitialspace=delimiter == " ", strict=True)
    start = stream.tell()
    cells = next(reader, None)

    # 説明行を飛ばすのは先頭だけ。列名行の#を誤って捨てない。
    while cells is not None and (
        not cells or any(cells[0].lstrip().startswith(prefix) for prefix in options.comment_prefixes)
    ):
        start = stream.tell()
        cells = next(reader, None)

    metadata: dict[str, Any] = {}
    for field in options.fields:
        if cells is None:
            raise SerializationError(f"ヘッダの項目が不足しています: {field.name}")
        has_padding = options.allow_padding and bool(cells) and all(value == "" for value in cells[1:])

        # 空白区切りではversion 1自体が複数セルになる。名前付き項目は元の行で解釈し、
        # 値に含まれる連続スペースや内側の引用符をCSVの分割結果から作り直さない。
        is_named_text = delimiter == " " and field.separator is not None and len(cells) > 1 and not has_padding
        if is_named_text:
            field_text = text[start:stream.tell()].rstrip("\r\n")
        else:
            if len(cells) != 1 and not has_padding:
                raise SerializationError(f"ヘッダ{field.name}: 値は1セルです。末尾空セルにはallow_paddingを指定できます")
            field_text = cells[0]

        value = _field_value(field_text, field)
        _add_values(metadata, {field.name: value}, empty_as_none=options.empty_as_none)
        # 最後の項目では先読みせず、列名行を本文へ残す。
        if len(metadata) < len(options.fields):
            start = stream.tell()
            cells = next(reader, None)
    return metadata, stream.read()


def split_header(text: str, options: HeaderOptions, delimiter: str) -> tuple[dict[str, Any], str]:
    """ 確定した設定から読取手順を選ぶ。設定同士の組合せ検証は行わない。
    """
    # 項目名・順序を宣言した形式と、ファイルからkey/valueを集める形式をここで分ける。
    # 後者もセル形式かテキスト形式かを設定で選び、本文の内容からは推測しない。
    try:
        if isinstance(options, CsvHeaderOptions):
            return _declared_values(text, options, delimiter)
        if options.separator is not None:
            return _text_values(text, options)
        return _csv_values(text, options, delimiter)
    except csv.Error as error:
        raise SerializationError(f"CSVヘッダのセルが不正です: {error}") from error


def _csv_values(text: str, options: CsvKeyValueHeaderOptions, delimiter: str) -> tuple[dict[str, Any], str]:
    """ CSVレコード単位でメタを読み、引用符内改行を件数へ含めない。
    """
    stream = StringIO(text, newline="")
    reader = csv.reader(stream, delimiter=delimiter, skipinitialspace=delimiter == " ", strict=True)
    metadata: dict[str, Any] = {}
    while options.row_count is None or len(metadata) < options.row_count:
        start = stream.tell()
        cells = next(reader, None)
        if cells is None:
            raise SerializationError("CSVメタの境界、または指定件数のメタがありません")

        raw = text[start:stream.tell()]
        is_blank = not cells or delimiter == " " and cells == [""] and not raw.strip()
        if options.boundary == "blank_line" and is_blank:
            break
        if options.boundary == "marker" and cells == [options.marker]:
            break

        if len(cells) != 2 or not cells[0].strip():
            raise SerializationError("CSVメタは空でないkeyとvalueの2列が必要です")
        _add_values(metadata, {cells[0]: cells[1]}, empty_as_none=options.empty_as_none)
    return metadata, stream.read()


def _text_values(text: str, options: CsvKeyValueHeaderOptions) -> tuple[dict[str, Any], str]:
    """ テキストヘッダは物理行で数え、空白を含む値の解釈を共通処理へ委譲する。
    """
    stream = StringIO(text, newline="")
    metadata: dict[str, Any] = {}
    row_count = 0
    while options.boundary != "fixed_rows" or row_count < (options.row_count or 0):
        line = stream.readline()
        if not line:
            raise SerializationError("テキストヘッダの境界または指定行数がありません")
        row_count += 1
        if options.boundary == "blank_line" and not line.strip():
            break
        if options.boundary == "marker" and line.strip() == options.marker:
            break
        if not line.startswith(options.prefix):
            raise SerializationError("ヘッダの開始記号がありません")
        values = parse_header_line(line[len(options.prefix):], separator=options.separator or ":", multiple=options.multiple)
        _add_values(metadata, values, empty_as_none=options.empty_as_none)
    return metadata, stream.read()


def _validate_values(metadata: dict[str, Any]):
    """ CSVへ保存できる単一値だけを許可し、任意オブジェクトの文字列化を防ぐ。
    """
    for key, value in metadata.items():
        if not key.strip():
            raise SerializationError("CSVメタのキーは空白以外の文字列が必要です")
        if value is not None and not isinstance(value, (str, int, float, bool, date, datetime, Decimal, UUID)):
            raise SerializationError("CSVメタの値は単一値が必要です")


def _dump_fields(metadata: dict[str, Any], options: CsvHeaderOptions, delimiter: str) -> str:
    """ 宣言した項目だけを、各項目の書式と順序で生成する。
    """
    expected = {field.name for field in options.fields}
    missing = expected - metadata.keys()
    unexpected = metadata.keys() - expected
    if missing or unexpected:
        raise SerializationError(
            f"ヘッダのfieldsと保存するメタ項目が一致しません。不足={sorted(missing)}、余剰={sorted(unexpected)}。"
            "出力版へのメタ変換を確認してください"
        )
    _validate_values(metadata)
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n", quoting=csv.QUOTE_ALL if delimiter == " " else csv.QUOTE_MINIMAL)
    for field in options.fields:
        value = "" if metadata[field.name] is None else str(metadata[field.name])
        if field.separator is not None:
            if not value or value != value.strip() or any(c in value for c in '\r\n"\\'):
                value = json.dumps(value, ensure_ascii=False)
            joiner = " " if field.separator == " " else field.separator + (" " if field.separator else "")
            value = field.name + joiner + value
        writer.writerow([value])
    return output.getvalue()


def dump_header_text(metadata: dict[str, Any], options: HeaderOptions, delimiter: str) -> str:
    """ メタを生成して必要な終端を付ける。説明コメントの元配置は保存しない。
    """
    if isinstance(options, CsvHeaderOptions):
        return _dump_fields(metadata, options, delimiter)
    if options.row_count is not None and len(metadata) != options.row_count:
        raise SerializationError("CSVメタの件数がrow_countと一致しません")

    if options.separator is not None:
        result = dump_header(metadata, separator=options.separator, prefix=options.prefix)
    else:
        _validate_values(metadata)
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=delimiter, lineterminator="\n", quoting=csv.QUOTE_ALL if delimiter == " " else csv.QUOTE_MINIMAL)
        writer.writerows(metadata.items())
        result = output.getvalue()
        if options.boundary == "marker":
            writer.writerow([options.marker])
            return output.getvalue()

    if options.boundary == "blank_line":
        return result + "\n"
    if options.boundary == "marker":
        return result + (options.marker or "") + "\n"
    return result
