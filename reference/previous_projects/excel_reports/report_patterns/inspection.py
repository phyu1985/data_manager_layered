"""点検帳票のPython定義。毎回新しいReportSpecを生成する。"""
from reporting import Column, Comparison, PrintHeaderSpec, ReportSpec, SheetSpec


def build_inspection_spec(*, print_headers: bool = False) -> ReportSpec:
    """2シート分の帳票定義を返す。

    Args:
        print_headers: Trueなら共通項目のセル表示を止め、印刷用ヘッダーへ
            担当部署・指定タイトル・現在/総ページを表示する。
            Falseなら従来のセル上部に共通項目を表示する。

    Returns:
        温度一覧・電圧一覧を含む、新しい帳票定義。
    """
    spec = ReportSpec(
        sort_field="order", descending=False,
        sheets=[
            SheetSpec(
                name="温度一覧", logic="AND",
                conditions=[Comparison(field="kind", op="==", value="A"),
                            Comparison(field="temperature", op=">=", value=10)],
                headers=[Column(field="department", label="担当部署")],
                record_columns=[Column(field="record_id", label="管理番号"),
                                Column(field="equipment", label="設備名")],
                item_columns=[Column(field="temperature", label="温度"),
                              Column(field="pressure", label="圧力")],
                item_titles=["初期測定", "中間測定", "最終測定"],
            ),
            SheetSpec(
                name="電圧一覧", logic="OR",
                conditions=[Comparison(field="kind", op="==", value="B"),
                            Comparison(field="voltage", op=">=", value=100)],
                headers=[Column(field="department", label="担当部署")],
                record_columns=[Column(field="record_id", label="管理番号")],
                item_columns=[Column(field="voltage", label="電圧")],
                item_titles=["初回", "2回目", "3回目"],
            ),
        ],
    )
    if print_headers:
        for sheet in spec.sheets:
            sheet.show_table_headers = False
            sheet.print_header = PrintHeaderSpec(
                title=sheet.name + "（設備点検結果）",
                left="担当部署：{{header:department}}",
            )
    return spec

def build_standard_spec() -> ReportSpec:
    """標準パターン用に、印刷ヘッダーを有効にした新しい定義を返す。

    Returns:
        温度一覧・電圧一覧を含む帳票定義。
    """
    return build_inspection_spec(print_headers=True)
