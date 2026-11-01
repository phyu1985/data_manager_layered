# 保守性を優先した見直し

2026-11-01 / v0.4.0

## 今回変えた理由

以前のAnalysisEditorは、編集権・処理値の公開・ファイルの項目対応・保存まで担当していた。
利用側もeditor.presets.thresholdと書く必要があり、処理値を使うために編集管理の構造を知ることになっていた。

今回、編集用の中間クラスをなくした。次のコードでPresetsを直接扱える。

```python
analysis = AnalysisService(Path("analysis"))

with analysis.edit() as presets:
    presets.threshold = 110
    run_analysis(presets)  # 実アプリの解析関数
    analysis.save_settings(presets, overwrite=True)
```

presets.thresholdはAnalysisPresets自身のフィールドであり、転送用プロパティではない。
項目が増えてもEditorへ同じ項目を追加する必要はない。解析関数はファイルも編集権も知らずに済む。
編集権・維持項目・保存の手順はAnalysisServiceの内側に置く。

## ファイルの分担

| モジュール | ここで分かること・変更すること |
| --- | --- |
| examples/analysis_models.py | 加工・解析の必要項目と値の型 |
| examples/settings_versions.py | 旧キー名、既定値、維持・廃止対象、隣接版キャスト |
| examples/analysis_files.py | ファイル名、Presetsとの対応、対象別保存、初回失敗の後始末 |
| examples/analysis_workflow.py | 編集開始・終了、保存を許可する条件、加工例 |
| examples/report_export.py | 帳票明細の組立とCSV / JSONL / Excelへの振り分け |
| examples/external_updates.py | 保存済みの値の外部反映、失敗先の収集・再実行 |
| examples/run_analysis_workflow.py | これらをどの順に使うか |

クラスを一メソッドずつ分割したわけではない。「保存仕様を変える」「編集の寿命を変える」など、変更理由で分けた。
AnalysisFilesはファイル形式の解析をRepositoryへ、AnalysisServiceは保存内容の組立をAnalysisFilesへ委譲する。
業務クラスの継承チェーン、汎用的なサービス基底クラス、プラグイン登録基盤は追加していない。

## 原則をどう適用したか

### 単一責任と委譲

編集の手順から、ファイルの項目対応と後始末を取り出した。
外部反映も、以前のようにEditorの内部構造を調べず、analysis.saved_snapshot()へ依頼する。
その内側で未保存値を避け、排他を保持したまま保存済みデータを読み直す。

### DRY

保存先の解決は既存のresolve_file_pathを再利用する。
保存済み解析データの組立はAnalysisFiles.loadへ一本化し、通常読取・編集開始・外部反映で同じ規則を使う。
ファイル名はAnalysisFilesで一度だけ決める。

一方、加工用と解析用のフィールド対応は、それぞれの目的が見えるよう明示している。
二つの対応表を反射や文字列による自動マッピングへまとめると、必要項目や型の誤りを追いにくくなるため採用しない。
版ごとに異なる検証規則も、短い重複があるだけで無理に汎用化しない。

### KISSと名前

辞書化はto_dict、階層展開はflatten_fields、復元はunflatten_fieldsとした。
短い処理ではdata / path / i等を使い、複数の意味が出る場所ではretained_values等で区別する。
名前の長さ自体を目標にしない。何を指すかを読む人が推測せずに済むことを優先する。

一行のdocstringも閉じる三重引用符を次の行へ置いた。
目的・前提はdocstringへ、排他を取る順序・保存対象の選択・削除対象の制限等の理由は該当コードの横へ置いている。

## 簡潔にしても残す保証

- 編集前にフォルダロックを取得し、終了まで保持する。
- 終了済み・別スレッド・別の編集で取得したPresetsの保存を拒否する。
- 閲覧用load()の値やmodel_copy()で作った別インスタンスを、現在の編集として保存しない。
- 初回失敗では今回の新規ファイルだけを削除し、後始末の失敗も報告する。
- 外部反映は未保存値を使わず、失敗しても解析データを巻き戻さない。
- 旧版キャスト、維持項目、廃止項目、変更対象だけの保存は従来の規則を維持する。

管理用Editorをなくした代わりに、サービス内部で現在のPresetsと所有スレッドを一つだけ記録する。
この小さな状態は誤保存防止のために残した。処理値を複製したり、個々の項目を代理公開したりはしない。

## 変更箇所を探す例

- 処理条件を追加：analysis_modelsと、必要なanalysis_filesの対応箇所。
- 過去ファイルへの互換性を変える：settings_versionsと、過去ファイルのテスト。
- 保存先・保存対象を変える：analysis_files。
- 編集をいつ始め、いつ終えるかを変える：analysis_workflowと画面側の呼出箇所。
- 帳票の列を変える：report_exportとExcel用アダプター。
- DBへの登録方法を変える：外部反映先の関数。SerializerやPresetsへDB処理を足さない。

実業務のモデル・DB・画面はこの例へまだ移植していない。強制終了時の保存復旧等、以前から未実装の保証を今回追加したわけでもない。
