from datetime import datetime

import pytest

from app.zpl.templating import (
    TemplateError,
    VariableDef,
    extract_variables,
    merge_variable_defs,
    resolve_values,
    substitute,
)

NOW = datetime(2026, 3, 4, 5, 6)


def test_extract_variables_ordered_unique_without_builtins():
    text = "^FD{{ name }}^FS^FD{{sku}}^FS^FD{{name}} {{date}}^FS"
    assert extract_variables(text, "{{extra}}") == ["name", "sku", "extra"]


def test_substitute_values_and_builtins():
    text = "{{name}} {{date}} {{time}} {{unknown}}"
    assert substitute(text, {"name": "Box"}, now=NOW) == "Box 2026-03-04 05:06 {{unknown}}"


def test_merge_keeps_metadata_for_existing_names():
    existing = [
        {"name": "a", "label": "Alpha", "default": "x"},
        VariableDef(name="gone", label="Gone"),
    ]
    merged = merge_variable_defs(["a", "b"], existing)
    assert [d.name for d in merged] == ["a", "b"]
    assert merged[0].label == "Alpha"
    assert merged[0].default == "x"
    assert merged[1] == VariableDef(name="b")


def test_resolve_values_uses_defaults_and_reports_missing():
    defs = [VariableDef(name="a", default="1"), VariableDef(name="b"), VariableDef(name="c")]
    with pytest.raises(TemplateError) as exc:
        resolve_values(["a", "b", "c"], defs, {"b": "2"})
    assert exc.value.missing == ["c"]
    assert resolve_values(["a", "b"], defs, {"b": "2"}) == {"a": "1", "b": "2"}


def test_resolve_values_rejects_zpl_control_characters():
    with pytest.raises(TemplateError) as exc:
        resolve_values(["a"], [], {"a": "^XA"})
    assert "a" in exc.value.invalid


def test_resolve_values_types():
    defs = [
        VariableDef(name="n", type="number"),
        VariableDef(name="d", type="date"),
        VariableDef(name="opt", required=False),
    ]
    with pytest.raises(TemplateError) as exc:
        resolve_values(["n", "d", "opt"], defs, {"n": "abc", "d": "2026-13-01"})
    assert set(exc.value.invalid) == {"n", "d"}
    values = resolve_values(["n", "d", "opt"], defs, {"n": "1,5", "d": "2026-01-02"})
    assert values == {"n": "1,5", "d": "2026-01-02", "opt": ""}


def test_resolve_values_non_strict_skips_problems():
    assert resolve_values(["a", "b"], [], {"a": "ok", "b": "^bad"}, strict=False) == {"a": "ok"}


@pytest.mark.parametrize("value", ["20260102", "2026-13-01", "2026-1-2", "2026-01-02T10:00"])
def test_dates_must_be_strict_iso(value):
    with pytest.raises(TemplateError):
        resolve_values(["d"], [VariableDef(name="d", type="date")], {"d": value})


def test_substitute_zpl_escapes_field_hex_indicator():
    from app.zpl.templating import substitute_zpl

    zpl = "^XA^FO0,0^FH\\^FD{{path}}^FS^FO0,50^FD{{path}}^FS^FO0,90^FH^FD{{u}}^FS^XZ"
    result = substitute_zpl(zpl, {"path": "C:\\12AB", "u": "a_b"})
    assert result == ("^XA^FO0,0^FH\\^FDC:\\5C12AB^FS^FO0,50^FDC:\\12AB^FS^FO0,90^FH^FDa_5Fb^FS^XZ")


def test_substituted_hex_field_renders_the_literal_value():
    from app.render.lexer import decode_field_hex
    from app.zpl.templating import substitute_zpl

    filled = substitute_zpl("^FH\\^FD{{v}}^FS", {"v": "C:\\41"})
    data = filled.split("^FD", 1)[1].split("^FS")[0]
    assert decode_field_hex(data, "\\", encoding="utf-8") == "C:\\41"


def test_substitute_zpl_shows_unfilled_placeholders_as_written():
    from app.render.lexer import decode_field_hex
    from app.zpl.templating import substitute_zpl

    filled = substitute_zpl("^XA^FH_^FD_7E {{item_ab}}^FS^FD{{item_ab}}^FS^XZ", {})
    assert filled == "^XA^FH_^FD_7E {{item_5Fab}}^FS^FD{{item_ab}}^FS^XZ"
    assert decode_field_hex("_7E {{item_5Fab}}", "_", encoding="utf-8") == "~ {{item_ab}}"


def test_substitute_zpl_scopes_the_hex_indicator_to_its_field():
    from app.zpl.templating import substitute_zpl

    zpl = "^XA^FH#^FD{{a}}^FS^FD{{a}}^FS^FH^FD{{a}} {{date}}^FS^XA^FD{{a}}^XZ"
    result = substitute_zpl(zpl, {"a": "#_"}, now=datetime(2026, 1, 2))
    assert result == "^XA^FH#^FD#23_^FS^FD#_^FS^FH^FD#_5F 2026-01-02^FS^XA^FD#_^XZ"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999"])
def test_numbers_must_be_finite(value):
    from app.zpl.templating import validate_value

    assert validate_value(VariableDef(name="n", type="number"), value) == "must be a number"


def test_substitute_zpl_ignores_whitespace_after_field_hex():
    from app.zpl.templating import substitute_zpl

    assert substitute_zpl("^FH ^FD{{v}}^FS", {"v": "a b_c"}) == "^FH ^FDa b_5Fc^FS"


def test_substitute_zpl_ends_a_field_at_the_next_origin():
    from app.zpl.templating import substitute_zpl

    zpl = "^XA^FO0,0^FH^FDx^FO0,20^FD{{v}}^FS^FH^FT0,40^FD{{v}}^FS^XZ"
    result = substitute_zpl(zpl, {"v": "a_b"})
    assert result == "^XA^FO0,0^FH^FDx^FO0,20^FDa_b^FS^FH^FT0,40^FDa_5Fb^FS^XZ"


@pytest.mark.parametrize(
    "zpl",
    [
        "^XA^PW400^LL200^FO0,0^A0N,30^FH ^FD{{v}}^FS^XZ",
        "^XA^PW400^LL200^FO0,0^A0N,30^FH^FDx^FO0,50^A0N,30^FD{{v}}^FS^XZ",
        "^XA^PW400^LL200^FH^FO0,0^A0N,30^FD{{v}}^FS^XZ",
    ],
)
def test_substituted_zpl_renders_the_literal_value(zpl):
    from app.render.renderer import render_zpl
    from app.zpl.templating import substitute_zpl

    value = "a _41 b"
    filled = render_zpl(substitute_zpl(zpl, {"v": value}))
    plain = zpl.replace("^FH ", "").replace("^FH", "").replace("{{v}}", value)
    assert filled.png == render_zpl(plain).png


def test_values_with_control_prefixes_get_field_hex():
    from app.render.renderer import render_zpl
    from app.zpl.templating import field_variables, substitute_zpl

    zpl = "^XA^PW400^LL100^FO0,0^A0N,30^FDa_{{v}}^FS^FO{{x}},50^A0N,30^FD{{v}}^FS^XZ"
    assert field_variables(zpl) == {"v"}
    filled = substitute_zpl(zpl, {"v": "^XZ~", "x": "10"})
    # The whole field is escaped, its own "_" included, so it prints exactly as written.
    assert "^FH_^FDa_5F_5EXZ_7E^FS^FO10,50^A0N,30^FH_^FD_5EXZ_7E^FS" in filled
    plain = render_zpl("^XA^CI28^PW400^LL100^FO0,0^A0N,30^FDa_X^FS^XZ")
    escaped = render_zpl(filled.replace("^XA", "^XA^CI28", 1))
    assert escaped.warnings == plain.warnings == []


def test_values_with_control_prefixes_outside_field_data_are_refused():
    from app.zpl.templating import substitute_zpl

    with pytest.raises(TemplateError) as exc:
        substitute_zpl("^XA^FO{{x}},0^FDa^FS^XZ", {"x": "1^XZ"})
    assert "x" in exc.value.invalid


def test_resolve_values_allows_control_prefixes_for_field_variables():
    values = resolve_values(["a"], [], {"a": "1^2"}, field_only=["a"])
    assert values == {"a": "1^2"}


def test_fields_after_an_added_field_hex_are_still_escaped():
    from app.zpl.templating import substitute_zpl

    zpl = "^XA^FO1,1^FD{{a}}^FS^FO2,2^FH^FD{{b}}^FS^FO3,3^FD{{c}}^FS^XZ"
    filled = substitute_zpl(zpl, {"a": "x^y", "b": "p^q_r", "c": "s_t"})
    assert filled == ("^XA^FO1,1^FH_^FDx_5Ey^FS^FO2,2^FH^FDp_5Eq_5Fr^FS^FO3,3^FDs_t^FS^XZ")
