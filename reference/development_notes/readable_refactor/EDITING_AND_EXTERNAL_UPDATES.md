# 編集中の排他・初回保存・外部情報の更新

2026-11-01 / v0.4.0。構成を見直した理由はREADABILITY_REVIEW.mdを参照。

## 編集権と処理値を分ける

```python
analysis = AnalysisService(Path("analysis"))
with analysis.edit() as presets:
    presets.threshold = 110
    analysis.save_settings(presets, overwrite=True)
```

editは読み込み前にフォルダの.edit-session.lockをOSロックする。
処理へ渡すのはAnalysisPresets自身で、管理用Editorの内部をたどる必要はない。
編集権と維持項目はAnalysisServiceの内部状態として持ち、ファイル操作はAnalysisFilesへ委譲する。

保存後も編集権は維持し、with終了時に正常・例外のどちらでも解放する。
使用中ならportalockerのLockExceptionで拒否する。画面側では使用中と通知する。
ロックファイルの存在だけで使用中かを判定しない。解放後もファイルは残してよい。

非モーダル画面はExitStackを画面側で保持し、enter_context(analysis.edit())で取得する構成にできる。
画面を閉じる時だけでなく、画面作成失敗でもclose()を実行する。
読み込み直後にwithを抜け、画面だけ編集可能にしておく使い方はしない。

保存は現在の編集で取得した同じPresetsから、同じスレッドで行う。
終了済み・別の編集・閲覧用load()・model_copy()の値を保存するとRuntimeErrorになる。
処理で新しいモデルを作った場合も、保存する値は編集中のPresetsへ明示的に反映する。
値の一致ではなく、編集中の対象かどうかを確認して誤保存を防ぐ。

analysis.load()は閲覧・帳票用の現在値を返す。一式を読む間だけ同じフォルダロックを取る。
編集中は既に受け取ったpresetsを使い、改めてload()で二重取得しない。
一般の外部エディタ・Repositoryを直接呼ぶ別プログラムには、この編集ロックが強制されるわけではない。
手修正はアプリの編集終了後に行い、再び開いて読み直す。

旧版出力も同じ窓口から行う。

```python
with analysis.edit() as presets:
    analysis.save_settings(presets, path="settings_v2.json", target_version=2)
```

別フォルダへの出力は出力先の編集権も即時取得し、使用中なら書込を拒否する。
待機し続けるロック順序を作らない。

## 初回保存の失敗

```python
analysis.save_initial(presets, retained_values=retained)
```

サービスが編集ロックを保持し、AnalysisFilesへ初回一式の保存を依頼する。
settings.yamlとmeasurements.jsonlの両方が新規対象であることを先に確認する。
途中で失敗したら、今回保存を試みたデータファイルだけを逆順で削除する。
元データ、既存ファイル、別用途のファイル、sidecar、フォルダ全体は削除しない。

後始末が成功したら元の保存例外を返す。削除にも失敗したら、保存失敗と削除失敗を
例外グループで返し、削除できなかったパスを例外のnoteに残す。
Pythonで処理できるCtrl+Cも後始末するが、強制終了・電源断では実行できない。
残った必要ファイルがある場合、初回保存の再試行は上書きせず拒否する。

これは既存ファイルの差分更新や、複数ファイルの原子的保存ではない。
同じフォルダの編集権を取得するすべての利用側が、この規則に従う前提。

## 保存後の外部反映と、更新ボタン

```python
updates = ExternalUpdateService(analysis, targets={
    "summary": create_summary_writer(Path("latest_status")),
    # "database": update_database,
})

with analysis.edit() as presets:
    presets.threshold = 110
    analysis.save_settings(presets, overwrite=True)
    result = updates.refresh(presets=presets)

# 編集画面を閉じた後の「外部情報を更新」ボタン
result = updates.refresh()
```

編集中に渡すpresetsは権利確認にだけ使い、analysis.saved_snapshot()で保存済みデータを読み直す。
未保存の変更を送信したり、画面の未保存値を破棄したりしない。
外部反映中もフォルダの編集権を保持し、同じデータの更新との競合を防ぐ。

保存と外部反映は明示的に順に呼ぶ。save_settings単体が外部反映を自動実行するわけではない。
具体的な呼出順はrun_analysis_workflow.pyにある。

戻り値はsucceeded_targetsとfailuresを持つ。失敗先名と元例外を残し、loggerへも出力する。
一つの接続先が失敗しても他の接続先は実行し、保存済み解析データは巻き戻さない。
失敗した接続先だけ再試行する場合は、ボタン等の操作時に次を呼ぶ。

```python
failed_names = [failure.target for failure in result.failures]
retry_result = updates.refresh(target_names=failed_names)
```

常設の反映待ち表示や、自動再試行キューは追加しない。画面通知とログファイル設定は実アプリ側で行う。
未登録の接続先・不正な編集対象・解析データの読取失敗は、外部反映先の障害とは区別して例外を返す。

## 外部接続の保証範囲

- 集約JSONの更新例は同じ解析フォルダなら同じJSONを更新し、再試行でファイルを増やさない。
- 実行例ではanalysisとlatest_statusは同じ親フォルダの下にある。
- 集約値は保存済みの設定と測定数の例。実行中の進捗状態を推測していない。
- パスを識別子とする例なので、移動後も同一結果として扱う実業務では安定したデータIDへ置き換える。
- DBの一意キー・UPSERT・通信失敗時の確定状態は実アダプターの責務。任意のDB処理をサービスだけで重複しない処理にはできない。
- 外部処理には入力のコピーを渡し、接続先同士や画面の編集値を変更させない。
- 通信タイムアウトやGUIの実行スレッドは実アプリで設定する。別スレッドで処理するなら、そのスレッド側で編集権を取得する。
- 実DB・実画面、強制終了後の残骸復旧、既存データの複数ファイル一括更新、ネットワーク共有固有の排他は未実装・未確認。
