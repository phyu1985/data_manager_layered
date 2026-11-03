""" 以前の公開名からKV形式へ移行するための互換窓口。
"""
from DataManager.serializers.kv import KvOptions as CustomTextOptions, KvSerializer as CustomTextSerializer

__all__ = ["CustomTextOptions", "CustomTextSerializer"]
