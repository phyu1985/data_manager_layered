""" 誤った保存値と版指定を検出する。reportArgumentTypeが2件出ることが正解。
"""
from DataManager import VersionedObjectRepository
from typecheck.versioning_positive import Settings


def invalid_calls(repository: VersionedObjectRepository[Settings]):
    repository.save("settings.yaml", "wrong model")
    repository.save("settings.yaml", Settings(threshold=1), target_version="V1")
