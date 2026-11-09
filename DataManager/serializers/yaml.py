""" YAML文書を重ね、モデルの値と既存のコメント・キー順を共存させる。
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, SequenceNode
from ruamel.yaml.scalarbool import ScalarBoolean

from DataManager.errors import ConfigurationError, SerializationError
from DataManager.model_conversion import ModelBinding, ModelValue


@dataclass(frozen=True)
class YamlDumpOptions:
    """ YAMLの値の出力名と、文書の引用符・字下げを指定する公開設定。
    """

    by_alias: bool = False
    preserve_quotes: bool = True
    indent_mapping: int = 2
    indent_sequence: int = 4
    indent_offset: int = 2
    footer_fields: tuple[str, ...] = ()

    def __post_init__(self):
        """ 出力フィールドの静的な指定だけを、設定生成時に確認する。
        """
        footer_fields = self.footer_fields
        if any(not name.strip() for name in footer_fields) or len(set(footer_fields)) != len(footer_fields):
            raise ConfigurationError("footer_fieldsは空欄・重複のないフィールド名で指定してください")


class YamlSerializer:
    """ テンプレート・既存文書・値を重ね、YAMLを読み書きする。

    文書の意味とコメントの継承を担当する。既存文書をいつ読むか、
    どの範囲をロックするかはRepositoryが担当する。
    """

    def __init__(self, *, dump_options: YamlDumpOptions | None = None):
        self._dump_options = dump_options or YamlDumpOptions()

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def supports_document_merge(self) -> bool:
        return True

    def _create_yaml_handler(self) -> Any:
        """ 1回の操作で使うハンドラを作る。
        """
        # ruamelの状態を操作間で共有せず、異なるファイルの同時処理を干渉させない。
        handler: Any = YAML(typ="rt")
        handler.preserve_quotes = self._dump_options.preserve_quotes
        handler.indent(
            mapping=self._dump_options.indent_mapping,
            sequence=self._dump_options.indent_sequence,
            offset=self._dump_options.indent_offset,
        )
        return handler

    def _load_document(self, serialized_text: str) -> dict[str, Any]:
        """ 最上位が文字列キーのマッピングである文書だけを受け入れる。
        """
        try:
            handler = self._create_yaml_handler()

            # round-tripの値構築で循環エイリアスがNoneになる前に、構文ノードを検査する。
            syntax_tree: object = handler.compose(serialized_text)
            self._validate_yaml_aliases(syntax_tree, set())
            document: object = handler.load(serialized_text)
        except YAMLError as error:
            raise SerializationError(f"YAMLを解析できません: {error}") from error

        if document is None:
            return cast(dict[str, Any], CommentedMap())
        if not isinstance(document, Mapping):
            raise SerializationError("YAMLのトップレベルはマッピングである必要があります")
        mapping_value = cast(Mapping[object, Any], document)
        if not all(isinstance(key, str) for key in mapping_value):
            raise SerializationError("YAMLのキーはstrで指定してください")

        # 実体はCommentedMapのまま保持する。コメントAPIを使う箇所だけAnyで橋渡しする。
        self._to_plain_value(mapping_value, set())
        return cast(dict[str, Any], document)

    def _validate_yaml_aliases(self, node: object, ancestor_ids: set[int]):
        """ 値へ変換する前の構文木で、循環するエイリアスを拒否する。
        """
        if not isinstance(node, (MappingNode, SequenceNode)):
            return
        if id(node) in ancestor_ids:
            raise SerializationError("循環するYAMLエイリアスには対応していません")

        # ruamel固有のノードAPIはここで扱い、モデル復元側には持ち込まない。
        yaml_node: Any = node
        if isinstance(node, MappingNode):
            field_pairs = cast(list[tuple[object, object]], yaml_node.value)
            child_nodes = [item for field_pair in field_pairs for item in field_pair]
        else:
            child_nodes = cast(list[object], yaml_node.value)

        ancestor_ids.add(id(node))
        try:
            for child in child_nodes:
                self._validate_yaml_aliases(child, ancestor_ids)
        finally:
            ancestor_ids.remove(id(node))

    def _to_plain_value(self, value: object, ancestor_ids: set[int]) -> Any:
        """ 編集用ノードを通常の辞書・配列へ戻し、循環参照と不正なキーを拒否する。
        """
        if isinstance(value, dict):
            mapping_value = cast(dict[object, Any], value)
            if id(mapping_value) in ancestor_ids:
                raise SerializationError("循環するYAMLエイリアスには対応していません")
            ancestor_ids.add(id(mapping_value))
            try:
                result: dict[str, Any] = {}
                for key, item in mapping_value.items():
                    if not isinstance(key, str):
                        raise SerializationError("YAMLのキーはstrで指定してください")
                    result[str(key)] = self._to_plain_value(item, ancestor_ids)
                return result
            finally:
                ancestor_ids.remove(id(mapping_value))

        if isinstance(value, list):
            sequence_value = cast(list[object], value)
            if id(sequence_value) in ancestor_ids:
                raise SerializationError("循環するYAMLエイリアスには対応していません")
            ancestor_ids.add(id(sequence_value))
            try:
                return [self._to_plain_value(item, ancestor_ids) for item in sequence_value]
            finally:
                ancestor_ids.remove(id(sequence_value))

        # 編集用のスカラーも通常の型へ戻す。ScalarBooleanはintの派生なので先に判定する。
        if isinstance(value, (bool, ScalarBoolean)):
            return bool(value)
        if isinstance(value, str):
            return str(value)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return float(value)
        if value is None or isinstance(value, (bytes, date, datetime)):
            return value
        raise SerializationError(f"通常のYAML値として扱えない型です: {type(value).__name__}")

    def _trim_block_scalar_padding(self, document: Any, key: str, value: object):
        """ 保持する末尾改行と書式の空行が重なり、文字列の値が増えるのを防ぐ。
        """
        if (
            getattr(document.get(key), "style", None) not in ("|", ">")
            or not isinstance(value, str) or not value.endswith("\n\n")
        ):
            return
        comments = document.ca.items.get(key)
        if comments is None or comments[2] is None:
            return
        token = comments[2]
        trimmed = token.value.lstrip("\r\n")
        if trimmed.strip():
            token.value = trimmed
        else:
            comments[2] = None

    def _merge_document(self, destination: dict[str, Any], source: dict[str, Any], *, copy_comments: bool):
        """ マッピングを再帰的に重ね、配列と単一値は全体を置き換える。
        """
        destination_node: Any = destination
        source_node: Any = source

        if copy_comments:
            # 文書冒頭とキーごとのコメントは既存文書を優先し、ない箇所はテンプレートを残す。
            if source_node.ca.comment is not None:
                destination_node.ca.comment = deepcopy(source_node.ca.comment)
            if source_node.ca.end:
                destination_node.ca.end = deepcopy(source_node.ca.end)

        for field_name, field_value in source.items():
            if isinstance(field_value, dict):
                existing_value = destination.get(field_name)
                if not isinstance(existing_value, dict):
                    destination[field_name] = CommentedMap()
                self._merge_document(
                    destination[field_name], cast(dict[str, Any], field_value), copy_comments=copy_comments,
                )
            else:
                self._trim_block_scalar_padding(destination_node, field_name, field_value)
                destination[field_name] = deepcopy(field_value)

            if copy_comments and field_name in source_node.ca.items:
                destination_node.ca.items[field_name] = deepcopy(source_node.ca.items[field_name])

    def dumps(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ テンプレート・既存文書・モデル値を重ね、未指定の既存項目も残す。
        """
        return self._dump_document(value, model_binding, existing_text, template_text, exact_fields=False)

    def dumps_exact(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue], *,
        existing_text: str | None = None, template_text: str | None = None,
    ) -> str:
        """ 出力項目はモデル値に限定し、存続するキーの配置・コメントを再利用する。
        """
        return self._dump_document(value, model_binding, existing_text, template_text, exact_fields=True)

    def _keep_output_fields(self, document: dict[str, Any], values: dict[str, Any]):
        """ 全階層で廃止キーを除く。テンプレートの既定値からも復活させない。
        """
        for key in list(document):
            if key not in values:
                del document[key]
            elif isinstance(document[key], dict) and isinstance(values[key], dict):
                # YAMLアンカーで共有された辞書も、出力先ごとに独立して更新する。
                child: Any = deepcopy(document[key])
                child.yaml_set_anchor(None)
                document[key] = child
                self._keep_output_fields(document[key], values[key])

    def _ends_with_block_scalar(self, value: object) -> bool:
        """ ブロック文字列末尾の空行は値の一部なので、項目間の区切りと混同しない。
        """
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            return bool(mapping) and self._ends_with_block_scalar(list(mapping.values())[-1])
        if isinstance(value, list):
            items = cast(list[object], value)
            return bool(items) and self._ends_with_block_scalar(items[-1])
        return getattr(value, "style", None) in ("|", ">")

    def _mapping_prefixes(
        self, document: dict[str, Any], lines: list[str], parent: tuple[str, ...] = (),
    ) -> dict[tuple[str, ...], tuple[int, list[str]]]:
        """ キー直前の空行と独立したコメントを、モデルの値から分けて記録する。
        """
        node: Any = document
        if node.fa.flow_style():
            return {}
        prefixes: dict[tuple[str, ...], tuple[int, list[str]]] = {}
        previous: object = None
        for key, value in document.items():
            path = (*parent, key)
            location = node.lc.key(key)
            if location is not None and not self._ends_with_block_scalar(previous):
                line, column = int(location[0]), int(location[1])
                start = line
                while start > 0:
                    candidate = lines[start - 1]
                    indent = len(candidate) - len(candidate.lstrip())
                    if candidate.strip() and not (candidate.lstrip().startswith("#") and indent <= column):
                        break
                    start -= 1
                prefixes[path] = (line, [item.rstrip("\r\n") + "\n" for item in lines[start:line]])
            if isinstance(value, dict):
                prefixes.update(self._mapping_prefixes(cast(dict[str, Any], value), lines, path))
            previous = cast(object, value)
        return prefixes

    def _restore_mapping_prefixes(self, text: str, desired: dict[tuple[str, ...], list[str]]) -> str:
        """ 配列置換で失う節の区切りを戻す。文字列と配列要素内の配置には触れない。
        """
        if not desired:
            return text
        lines = text.splitlines(keepends=True)
        actual = self._mapping_prefixes(self._load_document(text), lines)
        replacements: dict[tuple[int, int], list[str]] = {}
        for path, prefix in desired.items():
            if path not in actual:
                continue
            line, existing = actual[path]
            old_comments = [item.strip() for item in existing if item.strip()]
            new_comments = [item.strip() for item in prefix if item.strip()]
            if old_comments == new_comments or not old_comments:
                replacement = prefix
            elif not new_comments:
                # テンプレートの空行だけを戻す場合も、既存の独立コメントは残す。
                first_comment = next(i for i, item in enumerate(existing) if item.strip())
                replacement = prefix + existing[first_comment:]
            else:
                missing = [item for item in prefix if item.strip() and item.strip() not in old_comments]
                replacement = existing + missing
            replacements[(line - len(existing), line)] = replacement

        # パーサーが示したキー境界だけを書き換え、値中の改行や#を区切りと誤認しない。
        for (start, end), replacement in sorted(replacements.items(), reverse=True):
            lines[start:end] = replacement
        return "".join(lines)

    def _dump_document(
        self, value: ModelValue, model_binding: ModelBinding[ModelValue],
        existing_text: str | None, template_text: str | None, *, exact_fields: bool,
    ) -> str:
        # まず書式の土台を作る。既存文書のコメントをテンプレートより優先する。
        document = self._load_document(template_text or "")
        # 文書先頭のコメントはruamelの文書コメントへ残し、末尾フィールドと一緒に複製しない。
        prefixes = {
            path: prefix for path, (_, prefix) in self._mapping_prefixes(document, (template_text or "").splitlines(keepends=True)).items()
            if prefix and not (path == (next(iter(document), None),) and path[0] in self._dump_options.footer_fields)
        }
        if existing_text is not None:
            existing = self._load_document(existing_text)
            prefixes.update({
                path: prefix for path, (_, prefix) in self._mapping_prefixes(existing, existing_text.splitlines(keepends=True)).items()
                if prefix and not (path == (next(iter(existing), None),) and path[0] in self._dump_options.footer_fields)
            })
            self._merge_document(document, existing, copy_comments=True)

        data = model_binding.to_dict(value, by_alias=self._dump_options.by_alias)
        self._to_plain_value(data, set())

        # 版変換後の辞書が保存仕様の正本。既存文書は書式だけに利用する。
        if exact_fields:
            self._keep_output_fields(document, data)
        self._merge_document(document, data, copy_comments=False)

        # 本文と維持項目の順序を分ける。フィールド名は利用側の設定で指定する。
        node: Any = document
        footer = [name for name in self._dump_options.footer_fields if name in document]
        for name in footer:
            node.move_to_end(name)
        if footer and len(footer) < len(document):
            path = (footer[0],)
            prefix = prefixes.get(path, [])
            prefixes[path] = prefix if prefix and not prefix[0].strip() else ["\n", *prefix]

        # 値の反映を終えた編集用文書を、最後にYAML文字列へ書き出す。
        output = StringIO()
        try:
            self._create_yaml_handler().dump(document, output)
        except YAMLError as error:
            raise SerializationError(f"YAMLへ変換できません: {error}") from error

        # 空行は配列の末尾要素に保持される場合があるため、値の置換後に区切りを戻す。
        return self._restore_mapping_prefixes(output.getvalue(), prefixes)

    def loads(self, serialized_text: str, model_binding: ModelBinding[ModelValue]) -> ModelValue:
        """ YAMLの値から、指定型のモデルまたは通常のdictを復元する。
        """
        document = self._load_document(serialized_text)
        # コメントを持つ編集用ノードを、利用側へ返す辞書に持ち出さない。
        return model_binding.restore_value(self._to_plain_value(document, set()))
