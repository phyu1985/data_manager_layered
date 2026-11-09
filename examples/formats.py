""" 各形式の実行例。波形は社内仕様と無関係な合成ヘッダーを使用する。
"""
import json
from pathlib import Path
import struct
from typing import Any, BinaryIO

from pydantic import BaseModel

from DataManager import ObjectRepository, RowsRepository, WaveformHeader, WaveformOptions, WaveformRepository


class User(BaseModel):
    id: str
    name: str


class Event(BaseModel):
    id: str
    message: str


def read_example_header(stream: BinaryIO) -> WaveformHeader:
    """ この実行例だけの長さ付きJSONを解析する。実際の社内形式ではない。
    """
    header_size = int.from_bytes(stream.read(4), "little")
    header_values = json.loads(stream.read(header_size))
    return WaveformHeader(values=header_values, data_offset=4 + header_size)


def main():
    output_directory = Path("outputs/formats")
    from DataManager.storage import Storage
    if Storage.find(output_directory) is None:
        Storage.initialize(output_directory)
    user = User(id="u1", name="Alice")
    user_repository = ObjectRepository(model=User, base_directory=output_directory)
    for extension in ("json", "yaml", "txt"):
        user_repository.save(f"user.{extension}", user)
        print(f"単一モデル({extension}):", user_repository.load(f"user.{extension}"))

    users_repository = RowsRepository(model=User, base_directory=output_directory)
    users_repository.save("users.csv", [user])
    print("CSV:", users_repository.load("users.csv"))

    event_repository = RowsRepository[User | Event](model=(User, Event), base_directory=output_directory)
    event_repository.save("events.jsonl", [user, Event(id="e1", message="started")])
    event_repository.append_jsonl("events.jsonl", [Event(id="e2", message="finished")])
    print("混在モデル:", [type(row).__name__ for row in event_repository.load("events.jsonl")])

    dictionary_repository = RowsRepository[dict[str, Any]](model=dict, base_directory=output_directory)
    dictionary_repository.save("dicts.jsonl", [{"empty": "", "none": None}, {}])
    print("辞書:", dictionary_repository.load("dicts.jsonl"))

    # 本番ではこの解析関数だけを社内側の実装へ差し替え、機密の境界規則を外へ出さない。
    example_header = json.dumps({"channels": [0], "samples": 2}).encode()
    example_data = len(example_header).to_bytes(4, "little") + example_header + struct.pack("<hhhh", 1, 2, 3, 4)
    (output_directory / "synthetic_wave.bin").write_bytes(example_data)
    waveform_repository = WaveformRepository(
        base_directory=output_directory, options=WaveformOptions(header_reader=read_example_header),
    )
    print("波形:", waveform_repository.load("synthetic_wave.bin").data.tolist())
    print("波形peek:", waveform_repository.peek("synthetic_wave.bin").tolist())
    print("保存先:", output_directory)


if __name__ == "__main__":
    main()
