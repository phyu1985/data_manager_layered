""" 社内仕様を含まない合成ヘッダーで、波形の復元と外部処理の接続を検証する。
"""
from dataclasses import replace
from io import BytesIO
import json
from typing import BinaryIO

import numpy as np
import pytest

from data_manager import (
    BinaryWaveformSerializer, ConfigurationError, WaveformDecryptError,
    WaveformFormatError, WaveformHeader, WaveformOptions, WaveformRepository,
)


def read_test_header(stream: BinaryIO) -> WaveformHeader:
    """ テスト専用の長さ付きJSONを読む。実際の社内ヘッダーとは関係しない。
    """
    header_size = int.from_bytes(stream.read(4), "little")
    values = json.loads(stream.read(header_size))
    return WaveformHeader(values=values, data_offset=4 + header_size)


def make_test_file(values, data_bytes):
    header_bytes = json.dumps(values).encode()
    return len(header_bytes).to_bytes(4, "little") + header_bytes + data_bytes


@pytest.mark.parametrize("endianness", ["little", "big"])
@pytest.mark.parametrize("signed", [True, False])
def test_waveform_restores_declared_dtype_and_shape(tmp_path, endianness, signed):
    dtype = ("<" if endianness == "little" else ">") + ("i2" if signed else "u2")
    original = np.array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]], dtype=dtype)
    data = make_test_file({"channels": [2, 5], "samples": 2, "endianness": endianness, "signed": signed}, original.tobytes())
    (tmp_path / "wave.bin").write_bytes(data)
    repository = WaveformRepository(base_directory=tmp_path, options=WaveformOptions(header_reader=read_test_header))
    restored = repository.load("wave.bin")
    np.testing.assert_array_equal(restored.data, original)
    assert restored.channel_order == [2, 5] and restored.path == (tmp_path / "wave.bin").resolve()
    assert restored.data.dtype == original.dtype and restored.data.flags.writeable
    np.testing.assert_array_equal(repository.peek("wave.bin"), original[:1])


def test_waveform_does_not_guess_utf8_boundary():
    data = make_test_file({"channel_mask": 0b101, "samples": 1}, b"\x00" * 8)
    value = BinaryWaveformSerializer(options=WaveformOptions(header_reader=read_test_header)).load(data)
    assert value.data.shape == (1, 2, 2) and value.channel_order == [0, 2]
    with pytest.raises(ConfigurationError, match="header_reader"):
        BinaryWaveformSerializer().load(data)


def test_peek_reads_only_the_first_sample(tmp_path):
    data = make_test_file({"channels": [0], "samples": 10000}, b"\x00" * 40000)
    (tmp_path / "wave.bin").write_bytes(b"encrypted")

    class TrackedStream(BytesIO):
        def read(self, size=-1):
            assert size >= 0, "peek must not read the full body"
            return super().read(size)

    decrypted = TrackedStream(data)
    options = WaveformOptions(header_reader=read_test_header, decrypt=lambda source: decrypted)
    restored = WaveformRepository(base_directory=tmp_path, options=options).peek("wave.bin")
    assert restored.shape == (1, 1, 2) and decrypted.closed
    restored[0, 0, 0] = 9


def test_shn_injects_decryptor_and_closes_its_stream(tmp_path):
    data = make_test_file({"channels": "1,3", "samples": 1}, b"\x00" * 8)
    (tmp_path / "wave.shn").write_bytes(b"ciphertext")
    decrypted = BytesIO(data)
    options = WaveformOptions(header_reader=read_test_header, decryptor=lambda source: decrypted)
    value = WaveformRepository(base_directory=tmp_path, options=options).load("wave.shn")
    assert value.channel_order == [1, 3] and decrypted.closed
    with pytest.raises(WaveformDecryptError):
        WaveformRepository(
            base_directory=tmp_path, options=replace(options, decryptor=None),
        ).load("wave.shn")


@pytest.mark.parametrize("header,body", [
    ({"channels": [0], "samples": 2}, b"\x00" * 4),
    ({"channels": [0], "samples": 1}, b"\x00" * 8),
    ({"channels": [0]}, b"\x00" * 3),
    ({"channels": []}, b"\x00" * 4),
    ({"channels": [0, 0]}, b"\x00" * 8),
    ({"channels": [0], "signed": "false"}, b"\x00" * 4),
    ({"channels": [0], "samples": 1.5}, b"\x00" * 4),
    ({"channel_mask": 0}, b"\x00" * 4),
])
def test_invalid_waveform_shape_is_not_truncated(header, body):
    with pytest.raises(WaveformFormatError):
        BinaryWaveformSerializer(options=WaveformOptions(header_reader=read_test_header)).load(make_test_file(header, body))


@pytest.mark.parametrize("offset", [-1, 999, True])
def test_invalid_offsets_are_rejected(offset):
    options = WaveformOptions(header_reader=lambda stream: WaveformHeader(values={"channels": [0]}, data_offset=offset))
    with pytest.raises(WaveformFormatError):
        BinaryWaveformSerializer(options=options).load(b"\x00" * 4)


def test_explicit_zero_samples_can_be_loaded_but_not_peeked(tmp_path):
    data = make_test_file({"channels": [0], "samples": 0}, b"")
    (tmp_path / "empty.bin").write_bytes(data)
    repository = WaveformRepository(base_directory=tmp_path, options=WaveformOptions(header_reader=read_test_header))
    assert repository.load("empty.bin").data.shape == (0, 1, 2)
    with pytest.raises(WaveformFormatError):
        repository.peek("empty.bin")
