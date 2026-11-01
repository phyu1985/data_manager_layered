# 以前のコード・図・説明・サンプルの保管

このフォルダは経緯と元資料を残すための保管場所です。現構成の正しい使い方はルートREADMEとdocsです。ここにある旧README、src/data_managerのimport、旧テスト結果を現在の仕様とは扱わないでください。

- previous_projects/data_manager_redesign: 元のRepository/Serializer、全実行例、説明・Mermaid図、テスト、残っていた合成出力。
- previous_projects/excel_reports: 元のExcelエンジン、帳票パターン、単体例、テスト、設計ガイド、テンプレート。
- previous_projects/simple_excel_reports: このチャットの元ワークスペースのコード・資料・出力例。
- development_notes: 作業用フォルダに残っていた各段階の提案・構造説明・図・検証記録。
- inventory.json: この収録時点のファイル名とSHA-256。実装は内容を変更せずコピーしました。過去Markdownのローカルリンクは収録先へ直し、説明文と集約JSONの個人用絶対パスは相対表記・プレースホルダーへ置き換えました。source_sha256は元ファイル、sha256は収録後の値です。

仮想環境、.git、キャッシュ、ロック、環境変数ファイルは除外しています。開発途中の同じ実装の複数コピーは現実装へ混ぜていません。元のディスク上のフォルダはそのままです。

元Excelの追加パターン機能には既存エンジンとの不整合が残っています。保管をもって対応完了とは扱いません。現在の動作確認済み実装はDataManager/Excel、対応済みの単体例はexamples/excel_reports.pyです。
