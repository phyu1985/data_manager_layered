""" データと設定の不整合。I/O・ロックの失敗は元の例外を保持する。
"""


class ConfigurationError(ValueError):
    """ モデル・形式の組み合わせなど、生成時の設定が不正。
    """


class SerializationError(ValueError):
    """ 形式の不正、型判別の失敗、予約キーとの衝突。
    """
