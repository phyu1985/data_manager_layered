""" AttributeBlockSerializerの移行用窓口。新規コードはBlockRowsSerializerを使う。
"""
from dataclasses import replace

from DataManager.errors import ConfigurationError
from DataManager.serializers.block_rows import BlockRowsOptions, BlockRowsSerializer


def AttributeBlockSerializer(*, attribute_count: int = 8, options: BlockRowsOptions | None = None) -> BlockRowsSerializer:
    """ 旧引数をrow_targetsへ読み替える互換ファクトリー。
    """
    if type(attribute_count) is not int or attribute_count < 1:
        raise ConfigurationError("この移行窓口のattribute_countは1以上の整数です")
    configured = options or BlockRowsOptions(delimiter=",")
    original = configured.columns or (
        ("name", "ch", "start", "length"),
        *((f"info_name{i + 1}", f"info_value{i + 1}", "start", "length") for i in range(attribute_count)),
        ("start_mm", "length_mm"),
    )
    if [len(group) for group in original] != [4] * (attribute_count + 1) + [2]:
        raise ConfigurationError("columnsは本体4列・指定件数の属性4列・寸法2列の構成です")
    columns = (original[0], *(("name", "value", "start", "length"),) * attribute_count, original[-1])
    targets = (None,) + ("attrs",) * attribute_count + (None,)
    return BlockRowsSerializer(options=replace(
        configured, columns=columns, row_targets=targets, header_columns=configured.header_columns or original,
    ))
