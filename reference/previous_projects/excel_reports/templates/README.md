# 帳票テンプレートの配置場所

`inspection_submission.xlsx` を提出用パターンで使用します。
`python example.py` の初回実行時に見本を作成します。既存ファイルは再生成しません。

見本をExcelで編集し、条件・列・位置別見出し・印刷ヘッダーを管理してください。
`report_patterns/registry.py` のパスだけが登録情報で、帳票内容の正本は.xlsxです。

見本を明示的に作り直す場合（編集済み内容は上書きされます）:

```python
from example import make_template
from report_patterns.registry import TEMPLATE_DIR

make_template(TEMPLATE_DIR / "inspection_submission.xlsx", print_headers=True)
```
