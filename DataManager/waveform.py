""" 社内側のヘッダー解析を注入し、独自バイナリを波形配列へ復元する。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.file_io import lock_file, resolve_file_path, validate_lock_timeout

WaveformArray = NDArray[np.int16] | NDArray[np.uint16]


@dataclass(frozen=True)
class WaveformHeader:
    """ 利用側のヘッダー解析が返す、正規化した項目と復号後のデータ開始位置。
    """

    values: Mapping[str, Any]
    data_offset: int


HeaderReader = Callable[[BinaryIO], WaveformHeader]
Decryptor = Callable[[BinaryIO], BinaryIO]


@dataclass(frozen=True)
class WaveformOptions:
    """ 波形の解析・復号の設定。境界の内部仕様はheader_reader側へ閉じ込める。
    """

    header_reader: HeaderReader | None = None
    endianness: Literal["little", "big"] | None = None
    signed: bool | None = None
    channel_source: Literal["auto", "list", "mask"] = "auto"
    decrypt: Literal["auto", "none", "shn"] | Decryptor = "auto"
    decryptor: Decryptor | None = None


class WaveformObject(BaseModel):
    """ 復元した波形。dataは(samples, channels, 2)の独立したNumPy配列。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    header: dict[str, Any]
    data: WaveformArray
    channel_order: list[int]
    path: Path
    meta: dict[str, Any] = Field(default_factory=dict)


class WaveformFormatError(SerializationError):
    """ ヘッダー項目、開始位置、サンプル幅、データ長の不整合。
    """


class WaveformDecryptError(SerializationError):
    """ 復号ハンドラの不足、失敗、復号後ストリームの不整合。
    """


def _parse_integer(value: object, field_name: str) -> int:
    """ ヘッダーの整数値を解釈し、浮動小数の切り捨てやboolの混入を拒否する。
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise WaveformFormatError(f"{field_name}は整数で指定してください")
    try:
        if isinstance(value, str) and value.lower().startswith(("0x", "0b")):
            return int(value, 0)
        return int(value)
    except ValueError as error:
        raise WaveformFormatError(f"{field_name}は整数で指定してください: {value!r}") from error


class BinaryWaveformSerializer:
    """ ヘッダー解析と復号を外部へ委譲し、波形本体を復元する読み取り専用Serializer。

    開始位置を推測しない。社内の解析関数は、汎用項目と開始位置だけを返せばよい。
    入力ストリームの寿命は操作単位で管理し、返す配列はストリームから独立させる。
    """

    def __init__(self, *, options: WaveformOptions | None = None):
        self._options = options or WaveformOptions()

    def _prepare_stream(self, source: BinaryIO, path: Path, resources: ExitStack) -> BinaryIO:
        """ 復号後の、seek可能なストリームを選ぶ。
        """
        decrypt = self._options.decrypt
        if decrypt == "auto":
            decrypt = "shn" if path.suffix.lower() == ".shn" else "none"
        if decrypt == "none":
            return source

        decryptor = decrypt if callable(decrypt) else self._options.decryptor
        if decryptor is None:
            raise WaveformDecryptError("復号が必要ですがdecryptorが指定されていません")

        try:
            decrypted_stream = decryptor(source)
            # 別のストリームを受け取った場合も、この操作の終了時に解放する。
            if decrypted_stream is not source:
                resources.callback(decrypted_stream.close)
            if not decrypted_stream.seekable():
                raise WaveformDecryptError("復号後のストリームはseek可能である必要があります")
            decrypted_stream.seek(0)
            return decrypted_stream
        except WaveformDecryptError:
            raise
        except Exception as error:
            raise WaveformDecryptError(f"復号処理に失敗しました: {error}") from error

    def _read_header(self, stream: BinaryIO) -> WaveformHeader:
        """ 外部解析の結果を受け取り、開始位置の基本条件を確認する。
        """
        header_reader = self._options.header_reader
        if header_reader is None:
            raise ConfigurationError("正式な境界を求めるheader_readerを指定してください")

        # 社内固有の項目名や位置の計算方法は、このコールバックから持ち出さない。
        stream.seek(0)
        try:
            parsed_header = header_reader(stream)
        except Exception as error:
            raise WaveformFormatError(f"ヘッダー解析に失敗しました: {error}") from error

        return self._validate_header_result(parsed_header)

    def _validate_header_result(self, result: object) -> WaveformHeader:
        """ 外部処理の返却値を確認し、ライブラリ側で扱えるヘッダーへ揃える。
        """
        if not isinstance(result, WaveformHeader):
            raise WaveformFormatError("header_readerはWaveformHeaderを返してください")
        if type(result.data_offset) is not int or result.data_offset < 0:
            raise WaveformFormatError("data_offsetは0以上の整数で指定してください")

        # 外部関数の注釈だけを信用せず、実際の構造を確認してから項目を参照する。
        header_values = cast(object, result.values)
        if not isinstance(header_values, Mapping):
            raise WaveformFormatError("WaveformHeader.valuesはマッピングで指定してください")

        normalized_values: dict[str, Any] = {}
        for field_name, field_value in cast(Mapping[object, Any], header_values).items():
            if not isinstance(field_name, str):
                raise WaveformFormatError("WaveformHeader.valuesのキーはstrで指定してください")
            normalized_values[field_name] = field_value

        return WaveformHeader(values=normalized_values, data_offset=result.data_offset)

    def _read_channels(self, header: Mapping[str, Any]) -> list[int]:
        """ 正規化したchannelsまたはchannel_maskを、並び順のあるリストへ戻す。
        """
        if self._options.channel_source in ("auto", "list") and "channels" in header:
            channel_values = header["channels"]
            if isinstance(channel_values, str):
                channel_values = [part.strip() for part in channel_values.split(",")]
            if not isinstance(channel_values, (list, tuple)):
                raise WaveformFormatError("channelsは整数の一覧またはカンマ区切り文字列です")
            channels = [
                _parse_integer(value, "channels")
                for value in cast(list[object] | tuple[object, ...], channel_values)
            ]
        elif self._options.channel_source in ("auto", "mask") and "channel_mask" in header:
            channel_mask = _parse_integer(header["channel_mask"], "channel_mask")
            if channel_mask <= 0:
                raise WaveformFormatError("channel_maskは正の整数で指定してください")
            channels = [index for index in range(channel_mask.bit_length()) if channel_mask & (1 << index)]
        else:
            raise WaveformFormatError("channelsまたはchannel_maskが必要です")

        if not channels or len(channels) != len(set(channels)) or any(value < 0 for value in channels):
            raise WaveformFormatError("チャネルは重複のない0以上の整数を1個以上指定してください")
        return channels

    def _read_array(
        self, stream: BinaryIO, header: WaveformHeader, *, first_sample_only: bool,
    ) -> tuple[WaveformArray, list[int], dict[str, Any]]:
        """ 正規化した項目を確認し、必要なデータだけを読み出す。
        """
        # ヘッダと明示オプションから、サンプルの幅・符号・バイト順を確定する。
        header_values = dict(header.values)
        channels = self._read_channels(header_values)
        endianness = self._options.endianness or header_values.get("endianness", "little")
        signed = self._options.signed if self._options.signed is not None else header_values.get("signed", True)
        if endianness not in ("little", "big") or type(signed) is not bool:
            raise WaveformFormatError("endiannessはlittle/big、signedはboolで指定してください")

        samples_hint = None
        if "samples" in header_values:
            samples_hint = _parse_integer(header_values["samples"], "samples")
            if samples_hint < 0:
                raise WaveformFormatError("samplesは0以上で指定してください")

        # 1サンプルはチャネルごとのshort型(x, y)。peekでは本体全体を読まない。
        bytes_per_sample = len(channels) * 4
        if not first_sample_only:
            stream.seek(0, 2)
            if header.data_offset > stream.tell():
                raise WaveformFormatError("data_offsetがファイル末尾より後になっています")
        stream.seek(header.data_offset)
        data_bytes = stream.read(bytes_per_sample) if first_sample_only else stream.read()

        if first_sample_only:
            if samples_hint == 0 or len(data_bytes) != bytes_per_sample:
                raise WaveformFormatError("データ部が1サンプルに満たない長さです")
            sample_count = 1
        else:
            if len(data_bytes) % bytes_per_sample:
                raise WaveformFormatError("データ長がサンプル幅で割り切れません")
            sample_count = len(data_bytes) // bytes_per_sample
            if samples_hint is not None and sample_count != samples_hint:
                raise WaveformFormatError("samplesの指定と実際のデータ長が一致しません")
            if sample_count == 0 and samples_hint != 0:
                raise WaveformFormatError("データ部が空です")

        # 長さの整合が取れた本体だけを、サンプル×チャネル×(x,y)の配列へ戻す。
        prefix = "<" if endianness == "little" else ">"
        data_type = np.dtype(prefix + ("i2" if signed else "u2"))
        array = np.frombuffer(data_bytes, dtype=data_type).reshape(sample_count, len(channels), 2)
        normalized_header = {**header_values, "endianness": endianness, "signed": signed}

        # frombufferの参照元が閉じても利用でき、呼び出し元が安全に編集できる配列を返す。
        return cast(WaveformArray, array.copy()), channels, normalized_header

    def _load_from_stream(self, source: BinaryIO, path: Path) -> WaveformObject:
        # 復号・ヘッダ解析・本体復元を同じ資源管理の中で完了させる。
        with ExitStack() as resources:
            # 必要なら復号し、ヘッダを読み取ってから波形本体を配列へ戻す。
            stream = self._prepare_stream(source, path, resources)
            header = self._read_header(stream)
            array, channels, header_values = self._read_array(stream, header, first_sample_only=False)
            return WaveformObject(header=header_values, data=array, channel_order=channels, path=path)

    def load_file(self, path: str | Path) -> WaveformObject:
        """ ファイルから、ヘッダーと全サンプルを復元する。
        """
        resolved_path = Path(path).resolve()
        with resolved_path.open("rb") as source:
            return self._load_from_stream(source, resolved_path)

    def load(self, data_bytes: bytes) -> WaveformObject:
        """ メモリ上のバイト列から、ヘッダーと全サンプルを復元する。
        """
        with BytesIO(data_bytes) as source:
            return self._load_from_stream(source, Path("<memory>"))

    def peek_first_sample(self, path: str | Path) -> WaveformArray:
        """ 全サンプルを読み込まず、先頭1サンプルだけを独立した配列で返す。
        """
        resolved_path = Path(path).resolve()
        with resolved_path.open("rb") as source, ExitStack() as resources:
            stream = self._prepare_stream(source, resolved_path, resources)
            header = self._read_header(stream)
            array, _, _ = self._read_array(stream, header, first_sample_only=True)
            return array


class WaveformRepository:
    """ 波形読み込みとpeekの排他・パス解決を行う読み取り専用の入口。
    """

    def __init__(
        self, *, base_directory: Path, options: WaveformOptions | None = None,
        lock_timeout_seconds: float = 10,
    ):
        validate_lock_timeout(lock_timeout_seconds)
        self._base_directory = base_directory.resolve()
        self._options = options or WaveformOptions()
        self._lock_timeout_seconds = lock_timeout_seconds

    def load(self, path: str | Path, *, options: WaveformOptions | None = None) -> WaveformObject:
        """ ロック中に波形ファイル全体を復元する。
        """
        # 対象パスと読取設定を確定し、この操作で使うSerializerを用意する。
        target_path = resolve_file_path(self._base_directory, path)
        serializer = BinaryWaveformSerializer(options=options or self._options)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            return serializer.load_file(target_path)

    def peek(self, path: str | Path, *, options: WaveformOptions | None = None) -> WaveformArray:
        """ ロック中に先頭1サンプルを読み、全件読み込みより軽いプレビューを返す。
        """
        # 対象パスと読取設定を確定し、この操作で使うSerializerを用意する。
        target_path = resolve_file_path(self._base_directory, path)
        serializer = BinaryWaveformSerializer(options=options or self._options)

        with lock_file(target_path, timeout_seconds=self._lock_timeout_seconds):
            return serializer.peek_first_sample(target_path)
