"""`{{variable}}` placeholders in ZPL and designer fields."""

import math
import re
from bisect import bisect_right
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from app.render.lexer import tokenize

VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.\-]*)\s*\}\}")
FORBIDDEN_CHARS = ("^", "~")
ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

BUILTINS: dict[str, Callable[[datetime], str]] = {
    "date": lambda now: now.strftime("%Y-%m-%d"),
    "time": lambda now: now.strftime("%H:%M"),
    "datetime": lambda now: now.strftime("%Y-%m-%d %H:%M"),
    "year": lambda now: now.strftime("%Y"),
}


class VariableDef(BaseModel):
    name: str
    label: str = ""
    default: str = ""
    required: bool = True
    type: Literal["text", "number", "date"] = "text"
    help: str = ""


class TemplateError(ValueError):
    def __init__(self, missing: list[str] | None = None, invalid: dict[str, str] | None = None):
        self.missing = missing or []
        self.invalid = invalid or {}
        parts = []
        if self.missing:
            parts.append("missing values for: " + ", ".join(self.missing))
        if self.invalid:
            parts.append("; ".join(f"{k}: {v}" for k, v in self.invalid.items()))
        super().__init__("; ".join(parts))


def extract_variables(*texts: str | None) -> list[str]:
    """Ordered unique variable names found in the texts, excluding built-ins."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in VAR_RE.finditer(text or ""):
            name = match.group(1)
            if name not in BUILTINS:
                seen.setdefault(name)
    return list(seen)


def merge_variable_defs(
    names: Iterable[str], existing: Iterable[VariableDef | dict]
) -> list[VariableDef]:
    """Keep metadata of variables that still exist and add defaults for new ones."""
    by_name = {}
    for item in existing:
        definition = item if isinstance(item, VariableDef) else VariableDef.model_validate(item)
        by_name[definition.name] = definition
    return [by_name.get(name) or VariableDef(name=name) for name in names]


def validate_value(
    definition: VariableDef, value: str, *, allow_control: bool = False
) -> str | None:
    """Return an error message, or None when the value is valid.

    ^ and ~ start ZPL commands; `allow_control` accepts them for variables used only in
    field data, where they are written as hex codes.
    """
    if not allow_control and any(ch in value for ch in FORBIDDEN_CHARS):
        return "must not contain '^' or '~'"
    if not value:
        return "is required" if definition.required else None
    if definition.type == "number":
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return "must be a number"
        if not math.isfinite(number):
            return "must be a number"
    if definition.type == "date":
        try:
            if not ISO_DATE_RE.fullmatch(value):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            return "must be a date (YYYY-MM-DD)"
    return None


def resolve_values(
    names: Iterable[str],
    definitions: Iterable[VariableDef | dict],
    provided: Mapping[str, str] | None,
    *,
    strict: bool = True,
    field_only: Iterable[str] = (),
) -> dict[str, str]:
    """Combine provided values with defaults and validate them.

    In strict mode a TemplateError is raised for missing or invalid values; otherwise
    unresolvable variables are simply left out. Variables in `field_only` are used only in
    field data, so their values may contain ^ and ~.
    """
    field_only = set(field_only)
    provided = provided or {}
    defs = {d.name: d for d in merge_variable_defs(names, definitions)}
    values: dict[str, str] = {}
    missing: list[str] = []
    invalid: dict[str, str] = {}
    for name, definition in defs.items():
        value = provided.get(name)
        if value is None or value == "":
            value = definition.default
        value = "" if value is None else str(value)
        error = validate_value(definition, value, allow_control=name in field_only)
        if error == "is required":
            missing.append(name)
            continue
        if error:
            invalid[name] = error
            continue
        if value or not definition.required:
            values[name] = value
    if strict and (missing or invalid):
        raise TemplateError(missing, invalid)
    return values


def _lookup(name: str, values: Mapping[str, str], now: datetime) -> str | None:
    """Value of a placeholder: provided values first, then built-ins; None if unknown."""
    if name in values:
        return values[name]
    if name in BUILTINS:
        return BUILTINS[name](now)
    return None


def substitute(text: str, values: Mapping[str, str], *, now: datetime | None = None) -> str:
    """Replace placeholders; unknown placeholders are left untouched."""
    now = now or datetime.now()

    def replace(match: re.Match[str]) -> str:
        value = _lookup(match.group(1), values, now)
        return match.group(0) if value is None else value

    return VAR_RE.sub(replace, text)


def field_hex_indicator(param: str) -> str:
    """The ^FH indicator given by the character after ^FH; "_" when there is none."""
    indicator = param[:1]
    return indicator if indicator and not indicator.isspace() and indicator not in "^~," else "_"


@dataclass(slots=True, frozen=True)
class _FieldData:
    start: int  # where the data of ^FD/^FV/^SN starts and ends in the ZPL
    end: int
    command: int  # where the command itself starts
    code: str
    indicator: str | None  # the field's ^FH indicator


@lru_cache(maxsize=4)
def _field_data(zpl: str) -> tuple[_FieldData, ...]:
    """The field data commands of the ZPL and the ^FH indicator of their field.

    Cached: checking the variables and filling them in look at the same template.
    """
    spans: list[_FieldData] = []
    indicator: str | None = None
    has_origin = has_data = False
    for command in tokenize(zpl):
        code = command.code
        # As in the renderer, ^FO/^FT start a new field once the current one has data.
        if code in ("XA", "FS") or (code in ("FO", "FT") and has_origin and has_data):
            indicator, has_origin, has_data = None, False, False
        if code in ("FO", "FT"):
            has_origin = True
        elif code == "FH":
            indicator = field_hex_indicator(command.params)
        elif code in ("FD", "FV", "SN"):
            has_data = True
            spans.append(_FieldData(command.start + 3, command.end, command.start, code, indicator))
    return tuple(spans)


def _hex_escape(text: str, indicator: str) -> str:
    """Write the indicator and the control prefixes as hex codes in a ^FH field."""
    for ch in dict.fromkeys((indicator, "^", "~")):
        text = text.replace(ch, f"{indicator}{ord(ch):02X}")
    return text


def field_variables(zpl: str) -> set[str]:
    """Variables used only in field data, where values may contain ^ and ~ (they are written
    as ^FH hex codes); anywhere else those characters would start ZPL commands."""
    spans = _field_data(zpl)
    starts = [span.start for span in spans]
    inside: set[str] = set()
    outside: set[str] = set()
    for match in VAR_RE.finditer(zpl):
        index = bisect_right(starts, match.start()) - 1
        in_data = index >= 0 and match.end() <= spans[index].end and spans[index].code != "SN"
        (inside if in_data else outside).add(match.group(1))
    return inside - outside


def substitute_zpl(zpl: str, values: Mapping[str, str], *, now: datetime | None = None) -> str:
    """Like `substitute`, but escapes values placed in fields that use ^FH.

    Inside a ^FH field the indicator (default "_") starts a hex escape, so a literal
    indicator in a value is written as its own hex code. Placeholders without a value are
    escaped the same way, so they print as they are written. A value with ^ or ~ in field
    data without ^FH gets a ^FH_ added to its field; anywhere else it is refused.
    """
    now = now or datetime.now()
    spans = _field_data(zpl)
    starts = [span.start for span in spans]

    def span_of(match: re.Match[str]) -> _FieldData | None:
        index = bisect_right(starts, match.start()) - 1
        if index >= 0 and match.end() <= spans[index].end:
            return spans[index]
        return None

    def value_of(match: re.Match[str]) -> str:
        value = _lookup(match.group(1), values, now)
        return match.group(0) if value is None else value

    # Field data that needs a ^FH added because a value brings ^ or ~ into it.
    needs_hex: set[int] = set()
    for match in VAR_RE.finditer(zpl):
        value = value_of(match)
        if not any(ch in value for ch in FORBIDDEN_CHARS):
            continue
        span = span_of(match)
        if span is None or span.code == "SN":
            raise TemplateError(invalid={match.group(1): "must not contain '^' or '~' here"})
        if span.indicator is None:
            needs_hex.add(span.start)

    def substituted(start: int, end: int) -> str:
        """zpl[start:end] with its placeholders filled in. Matches are searched in the whole
        string, so their positions line up with the field data spans."""
        out: list[str] = []
        last = start
        for match in VAR_RE.finditer(zpl, start, end):
            value = value_of(match)
            span = span_of(match)
            if span is not None and span.indicator is not None:
                value = _hex_escape(value, span.indicator)
            out += [zpl[last : match.start()], value]
            last = match.end()
        out.append(zpl[last:end])
        return "".join(out)

    def escaped_data(span: _FieldData) -> str:
        """The field data of `span` filled in and written entirely as ^FH_ data."""
        out: list[str] = []
        last = span.start
        for match in VAR_RE.finditer(zpl, span.start, span.end):
            out += [zpl[last : match.start()], value_of(match)]
            last = match.end()
        out.append(zpl[last : span.end])
        return "".join(_hex_escape(part, "_") for part in out)

    out: list[str] = []
    last = 0
    for span in spans:
        if span.start not in needs_hex:
            continue
        caret = zpl[span.command]
        out += [
            substituted(last, span.command),
            f"{caret}FH_{zpl[span.command : span.start]}{escaped_data(span)}",
        ]
        last = span.end
    out.append(substituted(last, len(zpl)))
    return "".join(out)
