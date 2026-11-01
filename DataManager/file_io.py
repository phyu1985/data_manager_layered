""" 協調するプロセス間の排他と、ファイル単位の保存。

置換先とは別のsidecarをロックする。ロック不能時のフォールバックは行わない。
全件保存と直接追記の保証は異なる。追記の途中でのI/O障害は復旧の対象になる。
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from math import isfinite
import os
from pathlib import Path
import tempfile
from typing import BinaryIO

import portalocker

from DataManager.errors import ConfigurationError


def validate_lock_timeout(timeout_seconds: float):
    """ 待機時間が有限の非負数であることを確認する。
    """
    if not isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ConfigurationError("lock_timeout_secondsは有限の0以上の値を指定してください")


def resolve_file_path(base_directory: Path, path: str | Path) -> Path:
    """ 入力パスを実際の保存先へ揃え、パス表記の違いでロックが分かれるのを防ぐ。
    """
    candidate_path = Path(path)

    # 絶対パスは呼び出し元の指定を使い、相対パスだけ基準ディレクトリに結び付ける。
    if not candidate_path.is_absolute():
        candidate_path = base_directory / candidate_path

    # パス表記の違いだけでsidecarロックが分かれないよう、実際の保存先へ揃える。
    return candidate_path.resolve()


@contextmanager
def lock_file(path: Path, *, timeout_seconds: float) -> Generator[None, None, None]:
    """ ファイルを操作する間、同じ保存先を扱う他の処理を待機させる。
    """
    validate_lock_timeout(timeout_seconds)

    path.parent.mkdir(parents=True, exist_ok=True)
    # 保存対象そのものは置換されるため、置換されないsidecarをロック対象にする。
    lock_file_path = path.with_name(path.name + ".lock")

    with portalocker.Lock(
        str(lock_file_path),
        mode="a",
        timeout=timeout_seconds,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    ):
        # 呼び出し元のwithブロックをこの排他範囲で動かし、例外時もロックを解放する。
        yield


@contextmanager
def lock_directory(directory: Path, *, timeout_seconds: float = 0) -> Generator[Path, None, None]:
    """ 同じフォルダの編集を、読み込み開始から終了まで一人に限定する。

    withの間保持する協調ロック。短時間のファイルI/Oロックとは役割が異なる。
    ロックファイルが残っていても、OSロックが解放されていれば再取得できる。
    """
    resolved_directory = directory.resolve()

    # データを置換しても編集権が途切れないよう、専用のsidecarを固定して使う。
    # 解放後もロックファイルは削除しない。待機中の別プロセスと対象を分裂させない。
    with lock_file(resolved_directory / ".edit-session", timeout_seconds=timeout_seconds):
        yield resolved_directory


def write_file_atomically(path: Path, content: bytes):
    """ バイト列を一時ファイルへ保存し、保存先を原子的に置き換える。

    呼び出し元が必要なロックを保持すること。失敗時も一時ファイルを片付ける。
    """
    # 置換が同じファイルシステム内で行われるよう、保存先と同じディレクトリへ作る。
    file_descriptor, temporary_file_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_file_path = Path(temporary_file_name)

    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        # 内容を書き出して同期できた場合だけ切り替え、途中までの内容を保存先へ見せない。
        os.replace(temporary_file_path, path)
    finally:
        # 成功時は置換で元の一時パスが消え、失敗時だけ一時ファイルが残る。
        temporary_file_path.unlink(missing_ok=True)


def read_last_nonblank_line(stream: BinaryIO) -> tuple[bytes, int]:
    """ 末尾の非空行と、その開始位置を返す。

    戻り値の行は改行を含まない。JSONとしての妥当性は呼び出し元で検証する。
    """
    read_position = stream.seek(0, os.SEEK_END)
    trailing_content = b""

    while read_position:
        # 最初の行は途中から読んだ可能性があるため、確定した行だけを調べる。
        read_size = min(read_position, 8192)
        read_position -= read_size
        stream.seek(read_position)
        trailing_content = stream.read(read_size) + trailing_content

        # 開始位置をバイト数で追えるよう、改行を含めて後ろから行を調べる。
        lines = trailing_content.splitlines(keepends=True)
        line_end_offset = read_position + len(trailing_content)

        for line_index in range(len(lines) - 1, -1, -1):
            line = lines[line_index]
            line_start_offset = line_end_offset - len(line)
            is_complete_line = read_position == 0 or line_index > 0

            if line.strip() and is_complete_line:
                return line.rstrip(b"\r\n"), line_start_offset

            line_end_offset = line_start_offset

    raise ValueError("JSONLファイルに非空行がありません")
