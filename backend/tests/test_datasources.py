import io
import json
from datetime import datetime

import pytest
from openpyxl import Workbook

from app.zpl.datasources import (
    DataSourceError,
    auto_map,
    build_rows,
    copies_column,
    detect_format,
    parse_data,
)
from app.zpl.templating import VariableDef


def xlsx_bytes(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def test_detect_format():
    assert detect_format(b"a,b", "data.CSV") == "csv"
    assert detect_format(b"x", "data.yml") == "yaml"
    assert detect_format(b"PK\x03\x04...") == "xlsx"
    assert detect_format(b'  [{"a": 1}]') == "json"
    assert detect_format(b"- a: 1\n") == "yaml"
    assert detect_format(b"a\tb\n1\t2") == "tsv"
    assert detect_format(b"a;b\n1;2") == "csv"


def test_csv_with_bom_semicolon_and_quoted_newline():
    content = '﻿name;note\n"Zażółć";"line1\nline2"\n;\n'.encode()
    table = parse_data(content, filename="x.csv")
    assert table.columns == ["name", "note"]
    assert table.rows == [{"name": "Zażółć", "note": "line1\nline2"}]


def test_csv_cp1250_fallback():
    table = parse_data("name\nżółw\n".encode("cp1250"), fmt="csv")
    assert table.rows == [{"name": "żółw"}]


def test_tsv():
    table = parse_data(b"a\tb\n1\t2\n", filename="x.tsv")
    assert table.rows == [{"a": "1", "b": "2"}]


def test_json_shapes():
    rows = [{"a": 1, "b": 1.0, "c": None, "d": True}]
    assert parse_data(json.dumps(rows).encode(), fmt="json").rows == [
        {"a": "1", "b": "1", "c": "", "d": "true"}
    ]
    wrapped = parse_data(json.dumps({"rows": [{"x": "y"}]}).encode(), fmt="json")
    assert wrapped.rows == [{"x": "y"}]


def test_yaml():
    table = parse_data(b"- name: A\n  qty: 2\n- name: B\n", filename="d.yaml")
    assert table.columns == ["name", "qty"]
    assert table.rows == [{"name": "A", "qty": "2"}, {"name": "B"}]


def test_xlsx_dates_and_numbers():
    content = xlsx_bytes(
        [["name", "when", "qty"], ["A", datetime(2026, 5, 1), 3.0], [None, None, None]]
    )
    table = parse_data(content, filename="d.xlsx")
    assert table.rows == [{"name": "A", "when": "2026-05-01", "qty": "3"}]


@pytest.mark.parametrize(
    ("content", "fmt", "message"),
    [
        (b"", "csv", "empty"),
        (b"a,b\n", "csv", "no data rows"),
        (b"{bad json", "json", "Invalid JSON"),
        (b'{"a": 1}', "json", "list of objects"),
        (b"[1, 2]", "json", "not an object"),
        (b"a: [", "yaml", "Invalid YAML"),
        (b"not excel", "xlsx", "Excel"),
    ],
)
def test_malformed_input(content, fmt, message):
    with pytest.raises(DataSourceError, match=message):
        parse_data(content, fmt=fmt)


def test_row_limit():
    content = b"a\n" + b"1\n" * 11
    with pytest.raises(DataSourceError, match="Too many rows"):
        parse_data(content, fmt="csv", max_rows=10)


def test_auto_map_and_copies_column():
    mapping = auto_map(["Product Name", "SKU", "Copies"], ["product_name", "sku", "price"])
    assert mapping == {"product_name": "Product Name", "sku": "SKU", "price": None}
    assert copies_column(["a", "Copies"]) == "Copies"
    assert copies_column(["a", "_copies"]) == "_copies"
    assert copies_column(["a"]) is None


def test_build_rows_validation_constants_and_copies():
    defs = [
        VariableDef(name="name"),
        VariableDef(name="price", type="number"),
        VariableDef(name="shop", default="Main"),
        VariableDef(name="note", required=False),
    ]
    rows = [
        {"n": "A", "p": "9.99", "c": "2"},
        {"n": "", "p": "abc", "c": "0"},
        {"n": "B^", "p": "1"},
    ]
    results = build_rows(
        rows,
        defs,
        {"name": "n", "price": "p", "shop": None, "note": None},
        {"note": "fixed"},
        copies_from="c",
    )
    assert results[0].valid
    assert results[0].values == {"name": "A", "price": "9.99", "shop": "Main", "note": "fixed"}
    assert results[0].copies == 2
    assert results[1].errors == [
        "name is required",
        "price must be a number",
        "copies must be a whole number between 1 and 1000",
    ]
    assert results[2].errors == ["name must not contain '^' or '~'"]
    assert results[2].copies == 1


@pytest.mark.parametrize("copies", ["inf", "1e999", "-inf", "nan"])
def test_non_finite_copies_are_row_errors(copies):
    results = build_rows([{"c": copies}], [], {}, copies_from="c")
    assert results[0].errors == ["copies must be a whole number between 1 and 1000"]


@pytest.mark.parametrize(("raw", "copies"), [("2.0", 2), ("1e1", 10)])
def test_whole_number_copies(raw, copies):
    results = build_rows([{"c": raw}], [], {}, copies_from="c")
    assert (results[0].copies, results[0].errors) == (copies, [])


def test_fractional_copies_are_row_errors():
    results = build_rows([{"c": "1.9"}], [], {}, copies_from="c")
    assert results[0].errors == ["copies must be a whole number between 1 and 1000"]
    assert results[0].copies == 1
