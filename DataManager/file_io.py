""" 協調するプロセス間の排他と、ファイル単位の保存。

管理領域に固定数のガードを置く。ロック不能時のフォールバックは行わない。
全件保存と直接追記の保証は異なる。追記の途中でのI/O障害は復旧の対象になる。
"""
from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
import hashlib
from math import isfinite
import os
from pathlib import Path
import tempfile
import time
from typing import BinaryIO

import portalocker

from DataManager.errors import ConfigurationError

CommitGuard = Callable[[Path], AbstractContextManager[None]]


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

    # パス表記の違いだけでガードが分かれないよう、実際の保存先へ揃える。
    return candidate_path.resolve()


@contextmanager
def lock_file(path: Path, *, timeout_seconds: float) -> Generator[None, None, None]:
    """ ファイルを操作する間、同じ保存先を扱う他の処理を待機させる。
    """
    validate_lock_timeout(timeout_seconds)

    path.parent.mkdir(parents=True, exist_ok=True)
    # 保存対象は置換されるため、管理領域の変化しないガードをロックする。
    from DataManager.storage import Storage

    storage = Storage.find(path.parent)
    if storage is not None:
        with storage.file_guard(path, timeout_seconds):
            yield
        return

    # 領域外の単独ファイル利用も、データの隣へ個別の.lockを並べない。
    directory = path.parent / ".data_manager_locks"
    directory.mkdir(exist_ok=True)
    bucket = int(hashlib.sha256(path.name.casefold().encode()).hexdigest()[:8], 16) % 64
    lock_file_path = directory / f"{bucket:02}.lock"

    with portalocker.Lock(
        str(lock_file_path),
        mode="a",
        timeout=timeout_seconds,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    ):
        # 呼び出し元のwithブロックをこの排他範囲で動かし、例外時もロックを解放する。
        yield


@contextmanager
def lock_directory(directory: Path, *, timeout_seconds: float = 0, force: bool = False) -> Generator[Path, None, None]:
    """ フォルダ単位の編集権の互換入口。保存時検証が必要ならStorage.editを使う。

    異常終了で残る所有者情報は自動破棄せず、force=Trueで明示的に引き継ぐ。
    """
    resolved_directory = directory.resolve()

    from DataManager.storage import EditConflictError, Storage

    validate_lock_timeout(timeout_seconds)
    storage = Storage.discover(resolved_directory)
    deadline = time.monotonic() + timeout_seconds
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(storage.edit(resolved_directory, force=force))
                break
            except EditConflictError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(remaining, 0.1))
        yield resolved_directory


def write_file_atomically(path: Path, content: bytes, *, commit_guard: CommitGuard | None = None):
    """ バイト列を一時ファイルへ保存し、保存先を原子的に置き換える。

    呼び出し元が必要なロックを保持すること。失敗時も一時ファイルを片付ける。
    """
    # 置換が同じファイルシステム内で行われるよう、保存先と同じディレクトリへ作る。
    file_descriptor, temporary_file_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_file_path = Path(temporary_file_name)

    try:
        # 保存先へ触れる前に、一時ファイルの内容を最後まで書き出して同期する。
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        # 内容を書き出して同期できた場合だけ切り替え、途中までの内容を保存先へ見せない。
        # 書出しを終えてから、編集権の確認と置換を同じ排他区間で行う。
        with commit_guard(path) if commit_guard is not None else nullcontext():
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
