# ファイル配置と旧構成の対応

| 旧ファイル・場所 | 現在の場所・役割 |
|---|---|
| data_manager_redesign/src/data_manager/ | DataManager/の汎用Repository・Serializer |
| examples/analysis_models.py | Domain/models.py |
| examples/analysis_workflow.py | UseCase/analysis.py、Domain/processing.py |
| examples/analysis_files.py | DataManager/analysis_files.py |
| examples/settings_versions.py | DataManager/settings_versions.py |
| examples/end_to_end.py | View/end_to_end.py、UseCase/end_to_end.py、Domainの各処理 |
| examples/report_export.py | Domain/reporting.py、DataManager/report_repository.py |
| examples/external_updates.py | UseCase/external_updates.py、DataManager/summary.py |
| excel_reports/reporting/ | DataManager/Excel/ |
| excel_reports/example.py | examples/excel_reports.py（現importへ変更） |
| example.py（各形式） | examples/formats.py |
| examples/application_services.py | examples/application_services.py |
| examples/run_analysis_workflow.py | examples/workflow.py |

DataManager内の一般的なファイルは、repositories.py（ファイル操作）、file_io.py（ロック・原子的置換）、model_conversion.py（モデルと辞書）、versioning.py（隣接版キャスト）、services.py（保存先を固定した窓口）、waveform.py（波形読取）です。

serializers/にはjson.py・yaml.py・custom_text.py・csv.py・jsonl.pyがあり、field_paths.pyがCSVの入れ子項目の列対応を担当します。DataManager/Excelにはapi.py・contracts.py・models.py・project.py・excel.py・template.pyと業務明細を橋渡しするadapter.pyがあります。

sample_dataは入力例、outputsは実行時出力（Git対象外）、testsは回帰テスト、typecheckは型検査用です。reference/previous_projectsには元の3フォルダのコード・説明・テンプレート・残っていた合成出力例を保存しています。仮想環境・Git履歴・キャッシュ・ロックは含めません。reference/development_notesには開発途中の図・説明も段階別に残しています。

現在の正しいimportはルートから`from DataManager ...`等です。reference内には古いsrcやexamplesを使った説明・コードがあり、現在の入口として使わないでください。元のディスク上のフォルダは変更しません。

## メタ付き一覧の追加

DataManager/documents.pyが共通のRowsDocument、serializers/csv.pyのCsvOptionsがCSVの境界規則を担当します。RepositoryとRowsFileServiceのload_document / save_documentはCSV・JSONL共通です。例はexamples/metadata.py、詳細は[METADATA.md](METADATA.md)です。

## 共有編集権と拡張形式

DataManager/storage.pyは保存領域の識別・編集権・保存確定時のガード、serializers/kv.pyは標準KVと既存コメントヘッダ、block_rows.pyは複数行レコードを担当します。sample_capture.pyは架空の2表CSV・位置依存入力の専用処理です。frames.pyはオプションのpandas変換です。詳細は[拡張形式](EXTENSION_GUIDE.md)と[共有編集権](SHARED_EDITING.md)を参照してください。

## 窓口の役割整理

DataManager/services.pyが汎用のFileService / FileReader / FileWriter、repositories.pyがRowsDocumentRepository、versioning.pyがVersionedObjectRepository / VersionedRowsRepositoryです。UseCase/analysis.pyはAnalysisWorkspace、processing.pyは加工入力の組立て、external_updates.pyはExternalUpdaterです。帳票はDataManager/report_repository.pyのReportRepositoryへ移し、report_export.pyは旧名の互換窓口です。詳細は[FILE_INTERFACES.md](FILE_INTERFACES.md)を参照してください。

attribute_blocks.pyは属性行とattrsの対応付け、examples/versioned_files.pyはYAMLの版別テンプレート・metaの版変換・属性行の例です。構成と保存順は[TEMPLATES_AND_VERSIONS.md](TEMPLATES_AND_VERSIONS.md)を参照してください。
