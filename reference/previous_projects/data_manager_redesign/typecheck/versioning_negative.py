""" 誤った保存値と版指定を検出する。reportArgumentTypeが2件出ることが正解。
"""
from data_manager import VersionedObjectService
from versioning_positive import Settings


def invalid_calls(service: VersionedObjectService[Settings]):
    service.save("settings.yaml", "wrong model")
    service.save("settings.yaml", Settings(threshold=1), target_version="V1")
