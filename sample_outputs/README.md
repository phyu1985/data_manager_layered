# 実行結果の見本

examples/README.mdの全実行例から生成した合成データです。CSV・JSONL・YAML・text・JSON・波形・Excel・互換出力を収録しています。実行時にはoutputsへ書き、この見本は変更しません。

demo-csv / demo-jsonl / demo-xlsxは全工程、formatsは各形式、servicesは用途別入出力、compatは旧版保存・外部反映・3種帳票、excelはコード方式・テンプレート方式の結果です。

compat/latest_status/example_status.jsonは機械に依存する絶対パスだけを相対表記に置き換えました。ロックは収録していません。Excelの見本とテンプレートは人工データです。

metadataはCSVの3種類の境界（blank / marker / fixed）とJSONLを、同一のメタモデル・本文モデルで保存した比較見本です。

extendedは人工の拡張形式の変換・版互換出力・正規化したKV・2表CSVの見本です。保存領域のIDや編集者情報、ガードは含めません。実行手順はdocs/EXTENSION_GUIDE.mdを参照してください。

versioned_filesは版別YAMLテンプレートと保存結果、meta・本文を変換したCSV/JSONL、属性8行のブロックです。yaml/templatesとyaml/dataで、雛形と保存先を分けています。
