# 配布物の検証と残る範囲

2026-11-01。Windows / Python 3.12.14で確認しました。

| 確認 | 結果 |
|---|---|
| Repository・Serializer・版変換・編集排他・外部反映・全工程・Excel | 269件成功 |
| 最低対応依存環境（Excel未導入） | 226件成功、Excel関連4件スキップ |
| Pyrightの通常対象 | エラー0、警告0 |
| 故意の型誤り | 4ファイルで3・3・2・2件のreportArgumentTypeを確認 |
| 自作パッケージなしの起動 | コピー先で旧モジュールを拒否し、PYTHONPATHなしで成功 |
| 起動入口 | main.py / python -m View.end_to_end の両方で成功 |
| 実行例 | 全工程3形式・各形式・用途別services・旧版保存/外部更新・Excelコード/テンプレートを実行 |
| レイヤ境界 | 絶対import、参照方向、計算層での表示禁止を確認 |
| コーディング規約 | 現4レイヤ・実行例・検証ツールのdocstring書式とNone戻り値表記をASTで確認 |

通常の型チェックは4レイヤ・main.py・examples・tools・正例の型確認コードです。Domain/UseCase/View、汎用DataManager、Excelアダプターはstrict、既存Excelエンジンと単体例・ツールはbasicです。すべてをstrict検証済みとは扱いません。

依存ライブラリの確認環境は、Pydantic 2.14.2、portalocker 3.2.0、ruamel.yaml 0.18.17、NumPy 2.5.4、pytest 9.2.0、Pyright 1.1.414、openpyxl 3.1.5です。下限側はPydantic 2.7.0、portalocker 2.8.0、ruamel.yaml 0.18.0、NumPy 1.26.0を使いました。

ローカル検証では既存の外部依存用Python環境を再利用し、Excel依存だけはツール実行時に同梱ランタイムの外部ライブラリを参照しました。プロジェクトの実装・設定へその検索パスは書き込んでいません。利用時はrequirements-dev.txtを自分の仮想環境へ入れて、READMEの手順で確認できます。GitHub Actionsは新しい環境への依存インストールから設定してありますが、実際のGitHub上での実行はまだ行っていません。

資料の収録・リンク・不要ファイルは`python tools/check_release.py`で、故意の型誤りは`python tools/check_negative_types.py`で再確認できます。reference内は過去版の保管であり、過去版をまとめて現コードとしてテストしているわけではありません。

未解決の実業務仕様、YAMLの版変換時のコメント、追記障害、複数ファイルの整合性、追加帳票パターンの移植範囲は[実装の範囲と未解決事項](docs/LIMITATIONS.md)に集約しました。
