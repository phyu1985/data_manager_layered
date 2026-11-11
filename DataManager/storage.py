""" 共有保存領域の入口と、取消可能なフォルダ編集権を管理する。

    編集中は所有者情報だけを保持する。短時間のOSロックで権利変更と保存確定を
    直列化し、失効した編集者の書込みを拒否する。SMB等での実機確認は別途必要。
"""
from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import socket
from typing import Any, cast
from uuid import uuid4

import portalocker

from DataManager.errors import ConfigurationError
from DataManager.file_io import write_file_atomically


class EditConflictError(portalocker.exceptions.LockException):
    """ 他のセッションが対象を編集中。強制引継ぎは呼出側が明示する。
    """


class EditRevokedError(RuntimeError):
    """ 編集権が失効したため、保存・終了時の他者の情報削除を拒否する。
    """


@dataclass(frozen=True)
class EditorInfo:
    """ 操作者の確認用情報。PIDや時刻を権利の有効性の根拠には使わない。
    """

    resource: str
    session_id: str
    user: str
    host: str
    process_id: int
    started_at: str


class Storage:
    """ 全クライアントが同じ保存領域から管理場所を決定する入口。

    初期化は明示操作。通常のopen/discoverで別の管理場所を自動作成しない。
    guard数・管理パスはプロトコルの固定値で、アプリ版ごとに変更しない。
    """

    _GUARD_COUNT = 32
    _CONTROL_NAME = "application_control"

    def __init__(self, root: Path):
        self._root = root.resolve()
        try:
            raw_descriptor: object = json.loads((self._root / "storage.json").read_text(encoding="utf-8"))
            if not isinstance(raw_descriptor, dict):
                raise ValueError("保存領域の識別情報は辞書が必要です")
            descriptor = cast(dict[str, Any], raw_descriptor)
            valid = (
                set(descriptor) == {"protocol", "storage_id"}
                and type(descriptor["protocol"]) is int and descriptor["protocol"] == 1
                and isinstance(descriptor["storage_id"], str) and bool(descriptor["storage_id"])
            )
            if not valid:
                raise ValueError("未対応の管理規約です")
            self._storage_id: str = descriptor["storage_id"]
        except (OSError, ValueError, KeyError) as error:
            raise ConfigurationError(f"保存領域を開けません: {self._root}") from error

        # 保存領域の識別を確認できた場合だけ、全端末共通の管理場所を使う。
        self._control = self._root / self._CONTROL_NAME
        if not (self._control / "guards").is_dir() or not (self._control / "editors").is_dir():
            raise ConfigurationError("管理フォルダがありません。保守担当者が保存領域を確認してください")

    @property
    def root(self) -> Path:
        return self._root

    @classmethod
    def initialize(cls, root: Path) -> Storage:
        """ 保守操作として保存領域を一度だけ作る。既存の識別情報は上書きしない。
        """
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        descriptor = root / "storage.json"
        if descriptor.exists():
            return cls(root)
        if cls.find(root.parent) is not None:
            raise ConfigurationError("保存領域の入れ子初期化はできません。既存の保存領域を使ってください")
        control = root / cls._CONTROL_NAME
        if control.exists():
            raise ConfigurationError("識別情報なしで管理フォルダが存在します。自動復旧はしません")

        # 識別情報を最後に作り、通常のdiscoverには初期化済みの領域だけを見せる。
        (control / "guards").mkdir(parents=True)
        (control / "editors").mkdir()
        # 実運用では全クライアント停止中に実行する。xモードで既存の定義を置換しない。
        with descriptor.open("x", encoding="utf-8") as stream:
            json.dump({"protocol": 1, "storage_id": uuid4().hex}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return cls(root)

    @classmethod
    def find(cls, path: Path) -> Storage | None:
        """ 親の固定マーカーを探す。データ一覧や編集者一覧は走査しない。
        """
        resolved = path.resolve()
        for parent in (resolved, *resolved.parents):
            if (parent / "storage.json").exists():
                return cls(parent)
        return None

    @classmethod
    def discover(cls, path: Path) -> Storage:
        """ 編集を開始する際は初期化済みの保存領域を必須にする。
        """
        storage = cls.find(path)
        if storage is None:
            raise ConfigurationError("保存領域が未設定です。先にStorage.initialize(root)を明示実行してください")
        return storage

    def _resource(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self._root):
            raise ConfigurationError("保存領域外は指定できません")
        relative = resolved.relative_to(self._root)
        if relative.parts and relative.parts[0] in {self._CONTROL_NAME, "storage.json"}:
            raise ConfigurationError("管理領域は解析対象として指定できません")
        # Windows/Linuxのマウント名をキーに含めない。大文字小文字の差は保守的に同一視する。
        return relative.as_posix().casefold()

    def _check_configuration(self):
        """ 稼働中にマーカーが消失・差替えされても、古い保存領域情報で継続しない。
        """
        current = Storage(self._root)
        if current._storage_id != self._storage_id:
            raise ConfigurationError("保存領域の識別情報が変更されました。アプリを終了して確認してください")

    def _digest(self, path: Path) -> str:
        return hashlib.sha256(f"{self._storage_id}/{self._resource(path)}".encode()).hexdigest()

    def _guard_path(self, path: Path, kind: str) -> Path:
        bucket = int(self._digest(path)[:8], 16) % self._GUARD_COUNT
        return self._control / "guards" / f"{kind}-{bucket:02}.lock"

    @contextmanager
    def _guard(self, path: Path, kind: str, timeout: float = 10) -> Generator[None, None, None]:
        with portalocker.Lock(
            str(self._guard_path(path, kind)), mode="a", timeout=timeout,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        ):
            yield

    @contextmanager
    def file_guard(self, path: Path, timeout: float) -> Generator[None, None, None]:
        """ 保存対象を置換しても変わらない管理領域内のファイルで排他する。
        """
        with self._guard(path, "file", timeout):
            yield

    def _owner_path(self, directory: Path) -> Path:
        return self._control / "editors" / f"{self._digest(directory)}.json"

    def _read_owner(self, directory: Path) -> EditorInfo | None:
        path = self._owner_path(directory)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise ConfigurationError("編集者情報を読み取れません。ロックなしの継続はしません") from error

        if not isinstance(value, dict):
            raise ConfigurationError("編集者情報が壊れています")
        try:
            fields = cast(dict[str, Any], value)
            if set(fields) != set(EditorInfo.__dataclass_fields__):
                raise ValueError("項目が一致しません")
            if (
                any(not isinstance(fields[key], str) for key in ("resource", "session_id", "user", "host", "started_at"))
                or type(fields["process_id"]) is not int
            ):
                raise ValueError("項目の型が一致しません")
            owner = EditorInfo(**fields)
            if owner.resource != self._resource(directory) or not owner.session_id:
                raise ValueError("対象が一致しません")
            return owner
        except (TypeError, ValueError) as error:
            raise ConfigurationError("編集者情報を解釈できません") from error

    def editor(self, directory: Path) -> EditorInfo | None:
        """ 存在だけでロック中と判断せず、短時間の排他中に所有者情報を読む。
        """
        with self._guard(directory, "editor"):
            return self._read_owner(directory)

    @contextmanager
    def edit(self, directory: Path, *, force: bool = False) -> Generator[EditSession, None, None]:
        """ 対象フォルダの編集権を取得し、終了時は自分の情報だけを片付ける。
        """
        self._check_configuration()
        directory = directory.resolve()
        owner = EditorInfo(self._resource(directory), uuid4().hex, getpass.getuser(),
                           socket.gethostname(), os.getpid(), datetime.now(timezone.utc).isoformat())

        # 短時間の排他内で権利を取得・引き継ぎ、編集期間はセッションIDで識別する。
        with self._guard(directory, "editor"):
            self._check_configuration()
            previous = self._read_owner(directory)
            if previous is not None and not force:
                raise EditConflictError(f"編集中です: {previous.user}@{previous.host} / {previous.started_at}")
            # force時も既存プロセスは終了させない。所有者を入れ替え、旧セッションの保存を失効させる。
            write_file_atomically(self._owner_path(directory), json.dumps(owner.__dict__).encode("utf-8"))

        # 編集自体はOSロックを持ち続けず、節目と保存確定時に権利を検証する。
        guard_path = self._guard_path(directory, "editor")
        session = EditSession(directory, owner, validate=lambda: self._check_token(directory, owner.session_id),
                              guard_key=(self._storage_id, guard_path.name), guard_path=guard_path)
        try:
            yield session
        finally:
            # 強制引継ぎ後は新所有者の情報を消さず、自分の権利だけを片付ける。
            with self._guard(directory, "editor"):
                current = self._read_owner(directory)
                if current is not None and current.session_id == owner.session_id:
                    self._owner_path(directory).unlink()

    def _check_token(self, directory: Path, session_id: str):
        self._check_configuration()
        current = self._read_owner(directory)
        if current is None or current.session_id != session_id:
            raise EditRevokedError("編集権が失効しました。共有データへ保存せず、読み直してください")


class EditSession:
    """ フォルダの編集権。保存確定時の検証に使い、OSロックは保持し続けない。
    """

    def __init__(
        self, directory: Path, owner: EditorInfo, *, validate: Callable[[], None],
        guard_key: tuple[str, str], guard_path: Path,
    ):
        self._directory = directory
        self._owner = owner
        self._validate = validate
        self._guard_key = guard_key
        self._guard_path = guard_path

    @property
    def owner(self) -> EditorInfo:
        """ 表示に必要な所有者情報だけを公開する。
        """
        return self._owner

    def check(self):
        """ 編集処理の節目で権利を確認する。保存時には別途同じ排他内で再確認する。
        """
        with self._guard_sessions([self]):
            pass

    @contextmanager
    def commit_guard(self, target: Path) -> Generator[None, None, None]:
        """ 別フォルダへ出力するときも、元の権利と出力先の権利を同時に確認する。
        """
        target = target.resolve()
        same_directory = target.parent == self._directory or (
            target.parent.exists() and self._directory.exists() and target.parent.samefile(self._directory)
        )
        # 編集開始時に確認済みでも、保存までに強制引継ぎされ得る。置換が終わるまで再確認を保護する。
        if same_directory:
            with self._guard_sessions([self]):
                yield
            return

        # 別フォルダへの出力は、元の編集権と出力先の編集権を両方確保する。
        other_storage = Storage.discover(target.parent)
        with other_storage.edit(target.parent) as destination:
            with self._guard_sessions([self, destination]):
                yield


    @staticmethod
    @contextmanager
    def _guard_sessions(sessions: Sequence[EditSession]) -> Generator[None, None, None]:
        """ 固定順で取得し、異なるマウント表記でも同じガードを二重取得しない。
        """
        guards = {session._guard_key: session._guard_path for session in sessions}
        with ExitStack() as stack:
            for key in sorted(guards):
                stack.enter_context(portalocker.Lock(str(guards[key]), mode="a", timeout=10,
                                                    flags=portalocker.LOCK_EX | portalocker.LOCK_NB))
            # 全ガードを取得してから確認し、権利確認と保存の間に引き継がせない。
            for session in sessions:
                session._validate()
            yield
