# 編集中の排他・初回保存の後始末・外部情報の更新

2026-11-01 / v0.3.1。アプリ側の動作例に合意内容を反映した。

## 何を解決するための構成か

ファイルの書込中だけロックしても、二つの画面が同じ古い内容を読み、
後から保存した画面が先の変更を消すことは防げない。
同じ解析データを一人だけが編集する運用に合わせ、フォルダ単位の編集権を
読み込み開始前から画面を閉じるまで保持する。

ファイル単位のロックと原子的書込は、その内側で引き続き使う。
汎用RepositoryはGUIの寿命を知らず、アプリ側の窓口が編集の開始・終了を管理する。
自動マージや版ごとの編集モデルは追加していない。

初回保存と再解析後の更新も分ける。初回は全必要ファイルが新規であることを確認し、
途中で失敗したら今回の作成物だけを片付ける。既存結果の差分更新にはこの削除処理を使わない。

外部反映は解析データ保存と別の成功条件を持つ。DB等の障害で保存済みの結果を戻さず、
保存済みデータから外部反映だけを再実行できるようにする。

## 編集する

```python
application = AnalysisApplicationService(Path("analysis"))

with application.edit_analysis() as editor:
    editor.presets.threshold = 110
    editor.save_settings(overwrite=True)
    # 測定値を変更した場合だけ、こちらも呼ぶ。
    # editor.save_measurements(overwrite=True)
```

withへ入るとフォルダの`.edit-session.lock`をOSロックし、その後に設定・測定値を読む。
使用中ならportalockerのLockExceptionが出る。UIでは「この解析データは使用中です」と通知する。
画面を閉じるまで長時間編集する場合も、その寿命に対応するwithの範囲をアプリ側で管理する。
読み込んだ直後にwithを抜け、画面だけ編集可能にしておく使い方はしない。

保存後も編集ロックは維持する。通常終了・例外終了のどちらでもwith終了時に解放する。
非モーダル画面ではExitStackを画面側で保持し、enter_context(application.edit_analysis())で取得して、画面終了・画面作成失敗のどちらでもclose()する構成にできる。
終了済みのeditorでの保存や、別スレッドからの操作はRuntimeErrorで拒否する。
新しい編集はedit_analysis()を呼び直す。

画面の編集値は`editor.presets`、維持対象は`editor.data.retained_values`にある。
旧版出力は同じ編集窓口から別名で行う。

```python
with application.edit_analysis() as editor:
    editor.save_settings(path="settings_v2.json", target_version=2)
```

別フォルダへ出力する場合は、そのフォルダの編集ロックも即時取得する。
出力先が編集中なら書込を拒否し、相互待ちを作らない。

`application.load_analysis()`は帳票等の閲覧用スナップショットを返す。
一式を読む間だけ同じフォルダロックを使うため、別画面の編集中には読み始めない。
保存用の旧API`application.save_settings(session)`はなくし、編集窓口からの保存へ変更した。

## 初回保存する

```python
application.save_initial(session)
```

1. フォルダの編集権を取得する。
2. settings.yamlとmeasurements.jsonlが両方とも新規保存先であることを確認する。
3. 順に保存する。
4. 失敗したら、今回保存を試みた新規データファイルだけを逆順で削除する。

元ファイル、既存データ、別用途のファイル、sidecarロックは削除しない。
ロックファイルは残してよい。存在ではなくOSロックの取得可否で使用中かを判定する。
ロックファイルを削除すると、待機中の別プロセスとの排他対象が分裂する場合がある。

後始末が成功したら元の保存例外をそのまま返す。
後始末にも失敗したら、保存失敗と削除失敗を例外グループ（通常はExceptionGroup）で返し、削除できなかったパスを例外のnoteへ残す。
Ctrl+CもPython側で例外を処理できる場合は後始末する。
画面では失敗を通知し、残骸がある場合に再保存成功として扱わない。

これは複数ファイルの原子的保存ではない。強制終了・電源断では後始末を実行できず、途中のデータが残り得る。
残った必要ファイルがある状態で初回保存を再試行すると、上書きせず拒否する。

## 外部反映とボタンの接続

```python
updates = ExternalUpdateService(application, targets={
    "summary": create_summary_writer(Path("latest_status")),
    # "database": update_database,  # 実DBの更新関数を用意した段階で接続する。
})

with application.edit_analysis() as editor:
    editor.presets.threshold = 110
    editor.save_settings(overwrite=True)
    result = updates.refresh_saved_data(edit_session=editor)

# 画面を閉じた後の「外部情報を更新」ボタンも、この処理を呼ぶ。
result = updates.refresh_saved_data()
```

編集中は既に取得したeditorを渡して二重ロックを避ける。
外部反映は保存済みファイルから読み直し、画面の未保存編集値は送らない。
未保存の値を持つ画面でも、その編集値を破棄・上書きしない。
他の解析フォルダのeditorや、終了済みのeditorは受け付けない。

ファイル保存と外部反映は明示的に順番に呼ぶ。保存メソッド単体が外部反映を自動実行するわけではない。
呼び出し順の実例はrun_analysis_workflow.pyにある。

戻り値は`succeeded_targets`と`failures`を持つ。失敗ごとに接続先名と元例外が残る。
一つの接続先が失敗しても他の接続先は実行し、解析データは巻き戻さない。
失敗先だけを再実行することもできる。

```python
if result.failures:
    # 実画面ではここで通知する。常設の「外部反映待ち」表示は要求しない。
    failed_names = [failure.target for failure in result.failures]
    retry_result = updates.refresh_saved_data(target_names=failed_names)
```

このコードはボタンの呼出例であり、失敗時に自動で繰り返すループではない。
外部反映エラーはexamples.external_updatesのloggerへも出力する。
ログファイルや通知ダイアログの設定は、実アプリ側で行う。
未登録の接続先やデータの読取失敗は、外部反映先の障害とは区別して例外を返す。

反映中もフォルダの編集権を保持し、同じ解析データが別画面から更新されるのを防ぐ。
実DBの更新関数では通信タイムアウト等を設定し、GUIを止める長い処理はアプリ側の実行設計に従って扱う。
editorを別スレッドへ渡さず、処理を実行するスレッド側で編集権を取得する。

## 今回動かしたものと、実アプリで決めるもの

- 集約JSONの更新例は実装済み。同じ解析フォルダなら同じJSONを上書きし、再試行でファイルを増やさない。
- 解析フォルダと集約用latest_statusは、実行例では同じ親フォルダの下にある。
- 集約内容は保存済みの設定・測定数の例。実行中の進捗状態を推測しているわけではない。
- 実DB・実画面は未接続。DBの一意キー、UPSERT、通信失敗時にどこまで書けたかの扱いは、実アダプターの責務。
- 集約JSON例は解析フォルダの正規化パスを識別子にする。移動後も同じ結果として扱う業務では保存データ内の安定したIDを使う。
- 同じコールバックに何度渡しても重複しないことは、接続先の更新関数が保証する。任意のDB処理をこのサービスだけで冪等にはできない。
- 一般の外部エディタ・直接Repositoryを呼ぶ別プログラムは編集ロックへ従うとは限らない。手修正はアプリの編集終了後に行い、再び開いて読み直す。
- 既存結果の複数ファイル同時更新、強制終了後の残骸復旧、ネットワーク共有固有の排他は別途確認が必要。
