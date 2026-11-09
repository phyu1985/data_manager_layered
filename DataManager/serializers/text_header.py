""" テキストヘッダのkey/valueを解釈する。本文と境界の扱いは各形式へ残す。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import re
from typing import Any
from uuid import UUID

from DataManager.errors import ConfigurationError, SerializationError


def validate_header_separator(separator: str):
    """ 空白区切り、または空白を含まない記号を受け付ける。
    """
    if not separator or separator != " " and any(character.isspace() for character in separator):
        raise ConfigurationError("ヘッダのseparatorは半角スペース、または空白のない文字列です")


def parse_header_line(line: str, *, separator: str, multiple: bool) -> dict[str, str]:
    """ 一行の文法を選ぶ。呼出側から直接渡せる区切り値は、この入口で確認する。
    """
    validate_header_separator(separator)
    if multiple:
        return _parse_pairs(line.strip(), separator)
    return _parse_pair(line.strip(), separator)


def _parse_pair(line: str, separator: str) -> dict[str, str]:
    """ 一対の区切りの後ろ全体を値にして、日時・パスのコロンを保持する。
    """
    parts = line.split(None, 1) if separator == " " else line.split(separator, 1)
    if len(parts) != 2 or not parts[0].strip():
        raise SerializationError("ヘッダは空でないkeyとvalueの組が必要です")
    key, value = (part.strip() for part in parts)
    if value.startswith('"'):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise SerializationError("ヘッダの引用文字列が不正です") from error
        if not isinstance(value, str):
            raise SerializationError("ヘッダの引用値は文字列が必要です")
    return {key: value}


def _parse_pairs(line: str, separator: str) -> dict[str, str]:
    """ 引用値と空白区切りの組を順に読み、キーの重複を拒否する。
    """
    # 次のキーを推測せず、一対ずつ消費する。値内の時刻・パスのコロンは区切らない。
    pattern = r"([^\s]+)\s+" if separator == " " else r"([^\s" + re.escape(separator) + r"]+)\s*" + re.escape(separator) + r"\s*"
    key_pattern = re.compile(pattern)
    values: dict[str, str] = {}
    position = 0
    while position < len(line):
        match = key_pattern.match(line, position)
        if match is None:
            raise SerializationError("ヘッダのkey/valueの並びが不正です。空白を含む値は引用してください")
        key = match.group(1)
        position = match.end()
        if position == len(line):
            value = ""
        elif line[position] == '"':
            try:
                value, consumed = json.JSONDecoder().raw_decode(line[position:])
            except ValueError as error:
                raise SerializationError("ヘッダの引用文字列が不正です") from error
            if not isinstance(value, str):
                raise SerializationError("ヘッダの引用値は文字列が必要です")
            position += consumed
            if position < len(line) and not line[position].isspace():
                raise SerializationError("ヘッダの各組の間には空白が必要です")
        else:
            end = position
            while end < len(line) and not line[end].isspace():
                end += 1
            value = line[position:end]
            position = end
        if key in values:
            raise SerializationError(f"ヘッダのキーが重複しています: {key!r}")
        values[key] = value
        while position < len(line) and line[position].isspace():
            position += 1
    return values


def dump_header(metadata: dict[str, Any], *, separator: str, prefix: str = "") -> str:
    """ 値を引用して一対一行で保存し、空白やコロンを含む値も復元できるようにする。
    """
    validate_header_separator(separator)
    lines: list[str] = []
    for key, value in metadata.items():
        if not key or any(character.isspace() for character in key) or separator != " " and separator in key:
            raise SerializationError("テキストヘッダのキーに空白・区切り文字は使えません")
        if value is not None and not isinstance(value, (str, int, float, bool, date, datetime, Decimal, UUID)):
            raise SerializationError("テキストヘッダの値は単一値が必要です")
        text = "" if value is None else str(value)
        encoded = json.dumps(text, ensure_ascii=False)
        joiner = " " if separator == " " else separator + " "
        lines.append(prefix + key + joiner + encoded + "\n")
    return "".join(lines)
