# CHANGELOG

## v1.0.0（2026-10-30）統合版

- v5の共通I/F（`ReportItem` / `ReportRecord[TItem]`）、`ReportGenerator`生成時の型整合性チェックを継承。
- `Comparison.source`によるRecord / Itemの抽出条件、AND/ORの混在判定。
- `Item.title`の照合キーと、Excel表示名`item_titles`の分離。シート別の`item_keys`による表示対象選択。
- `Record.items=[]`でもRecord条件で抽出できる空欄行の維持。
- B1空欄（ソートなし）、外部リンクの不継承（`keep_links=False`）。
- **統合時の追加修正**：テンプレートの連番等の数式を見本行から複製するとき、数式の種類を維持するよう`excel.py`を修正。ソースとなるテンプレート数式と業務データの文字列を区別する。
- READMEを確定仕様で全面整理。`docs/DESIGN.md`（設計方針）と`docs/TEMPLATE_SPEC.md`（Excel定義仕様）を追加。
- 数式複製および空Recordの追加テスト2件。

## ベース版からの経緯（参考）

- 初期版：1 Record＝1行、Itemの右方向展開、コード方式とExcelテンプレート方式。
- v2：タイトル一致で位置固定、B1空欄のソート停止。
- v3：`item_keys`と`item_titles`の分離、シートごとの必要Item選択。
- v4：Record条件とItem条件の混在、ItemなしRecordの抽出。
- v5：Record/Itemの基底I/F、`ReportGenerator`生成時の型検査。

この版は前回のv5 ZIPを基準に作成しました。手元のGitHubリポジトリで独自変更したファイル（例：設定シートのK～P列による追加ヘッダ定義）は含みません。
