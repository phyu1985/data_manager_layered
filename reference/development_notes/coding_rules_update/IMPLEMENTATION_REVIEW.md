# 既存実装の再利用・変更方針

2026-10-30 / 静的なコード確認に基づく。実動作テストはまだ実施していない。

## Text

実在するクラス名はJsonTextSerializer / YamlTextSerializer / CustomV0TextSerializer。
メモのJsonObjectSerializer等とは一致しない。
設定はJsonDumpOptions / YamlDumpOptions / CustomV0DumpOptions等。

再利用するもの:
- JSONのエンコード、YAMLのruamel.yamlを使った読み書き。
- YAMLのテンプレート→既存→モデル値というマージの基本方針。
- 独自v0のヘッダー・階層表現。ただし値の往復仕様は改めて検証する。

変更するもの:
- alias逆引きを無条件に実施しない。
- ファイルI/OをRepository側へ寄せ、dump_fileとRepositoryの二重管理を避ける。
- YAMLインスタンスの設定を書き換える状態共有は、操作単位の生成を候補にする。

要注意:
- CustomV0LoadOptions.sepはloadの処理へ渡されず、読み込みの区切りはドット固定。
- dumpは値を文字列化するため、None、bool、listなどの一般的な往復を保証できない。
- YAMLはコメント保持を目的にしているが、テンプレートと既存の両方がある場合のコメント継承は
  実際の文書で確認する必要がある。辞書値を再帰マージすることだけでは全コメント保持を保証できない。

## Table / Rows

両方にCSV / JSONLがあり、alias逆引き・階層展開・ファイルI/Oが重複している。
Tableをそのまま単一モデル用、Rowsを混在用として二重維持する構成は採らない。

再利用するもの:
- CSVのcsv.DictReader / DictWriter、JSONLの行ごとの解析。
- Rows側の列集合を全行から集める考え方。
- JSONLのメタと型情報を明示する考え方。

変更・廃止するもの:
- 公開ModelRegistryをモデル型指定に置き換える。
- mixedは本文と同じ階層のtypeキーを採用し、衝突を検出する。type/dataの包みは採用しない。
- _normalize_recordの一括加工を分解し、モデル検証と形式別の空欄処理を区別する。
- JSONLの空文字もNoneへ変換する既定を廃止する。
- 空dictや値がすべてNoneの行を黙って捨てる処理を廃止する。
- last_metaという可変の「直前読み込み結果」を持たず、検査で必要なメタを操作内で扱う。
- COLLECTのような結果を利用できない設定を初期APIへ移植しない。

確認した具体的な問題:
- JSONLLoadOptions.require_metaは定義されているが、loads内で必須チェックされていない。
- loadsのCOLLECTはローカル変数errorsへ収集しているが、呼び出し側へ返していない。
- 一括読み込みと逐次読み込みでエラーの既定が違う。
- TableのCSVは1行目のキーから列を決めるため、後続行だけにある可変dictのキーが落ちうる。
- alias変換は最上位だけで、CSVのドット区切りキーとネストしたモデルのaliasを一貫して扱えない。

## Repositories / I/O

再利用するもの:
- Objectのモデル型固定という考え方。
- 拡張子マッピング、同一ディレクトリでの一時ファイル置換。
- sidecarファイルによるロックという構造。

廃止・修正するもの:
- _AttrDict / _to_attrdict。
- Repositoryに形式ごとの既定値をコピーする処理。
- 存在しないiter_dumpsのProtocolと動的な有無判定。
- ロック不能時のno-opフォールバックと、本番の既定NullLock。
- 全件上書き時にwrite_meta=Falseとする分岐。
- 新規作成と追記で分かれている排他範囲。

確認した具体的な不整合:
- RowsRepositoryは空行・空文字等の設定名が実際のdataclassと異なり、未定義属性がNoneになる。
- Repositoryのmeta_models="default"はSerializerが認めるnone/tags/fullのいずれでもない。
- ObjectRepositoryのYAML既定値も、実際に必要なindent_mapping等と一致しない。

## Waveform

再利用するもの:
- 独自ヘッダー解析、NumPy配列化、復号ハンドラ、load / peek。

変更するもの:
- パッケージ外からの絶対importとtype ignoreを整理する。
- ロックは必須のI/O契約へ揃える。
- 実際に意味のないSKIP / COLLECTなどの設定は移植しない。

波形の全解析ロジックと実ファイルのテストは未完了。
読み取り専用であることと、peekで全件を読まないことを優先する。

## 初期範囲外

古いinterfaces.py / config.pyには、DataFrame、HDF5、SQLite、版管理、命名戦略の別構成もある。
現行のObject / Rows / Waveform再設計に一括で取り込まない。
__repositoriesとuowを含む旧構成も、自動的な移植対象にしない。
必要になった用途だけを個別に検討する。

