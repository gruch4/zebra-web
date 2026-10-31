"""Printer configuration commands embedded in label ZPL.

Label software (e.g. ZebraDesigner) embeds printer settings such as darkness, speed, media
type or print mode in the ZPL, often followed by ^JUS which stores them permanently.

Some of them belong to the label stock (media tracking, darkness, position) and are kept;
others belong to the printer hardware (e.g. whether the cutter is used) and are replaced by
the printer's own configuration. Which groups come from the label is configurable per
printer. Commands that change the printer permanently or perform actions (^JUS, calibration,
reset, ...) are always removed.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from app.render.lexer import tokenize

# Printer configuration and control commands (ZPL II Programming Guide Vol. 2, chapters 3
# and 5). Label layout commands such as ^PW, ^LL, ^LH, ^CI, ^PM and ^PQ are kept.
PRINTER_SETTINGS: dict[str, str] = {
    "MM": "print mode",
    "MN": "media tracking",
    "MT": "media type",
    "MD": "darkness",
    "SD": "darkness",
    "PR": "print speed",
    "LT": "label top",
    "LS": "label shift",
    "TA": "tear-off position",
    "PO": "print orientation",
    "SS": "media sensors",
    "MP": "front panel mode protection",
    "MF": "media feed",
    "ML": "maximum label length",
    "JS": "backfeed sequence",
    "XB": "backfeed suppression",
    "JZ": "reprint after error",
    "JU": "save or restore configuration",
    "SZ": "ZPL mode",
    "JT": "printhead test interval",
    "JN": "printhead test",
    "JO": "printhead test",
    "JC": "media calibration",
    "JG": "sensor profile",
    "JL": "label length calibration",
    "JR": "printer reset",
    "JA": "cancel all jobs",
    "JB": "flash memory initialisation",
    "JD": "communication diagnostics",
    "JE": "communication diagnostics",
    "PH": "label feed",
    "PP": "pause",
    "PS": "print start",
    "WC": "configuration label",
    "WL": "network configuration label",
    "KD": "display settings",
    "KN": "printer name",
    "KP": "front panel password",
    "NI": "network ID",
    "NC": "network connect",
    "NT": "network transparent",
    "SC": "serial port settings",
    "HS": "status query",
    "HI": "identification query",
    "HM": "memory query",
    "HH": "configuration query",
    "HQ": "status query",
    "HB": "battery status query",
    "HD": "head diagnostic query",
    "HF": "format upload",
    "HG": "graphic upload",
    "HU": "alert configuration query",
    "HW": "directory listing",
    "HY": "graphic upload",
    "HZ": "configuration query",
    # Commands that change the hardware, stored objects or the network setup, or that cancel
    # or pause other jobs (ZPL II Programming Guide, chapter 2).
    "SR": "printhead resistance",  # "Setting a higher value could damage the printhead"
    "ID": "object delete",
    "EG": "erase graphics",
    "CM": "memory letter designation",
    "KB": "battery discharge",
    "ZZ": "printer sleep",
    "JP": "pause and cancel format",
    "JX": "cancel current format",
    "RO": "reset counters",
    "KL": "display language",
    "NS": "network settings",
    "NB": "network boot",
    "NN": "network SNMP settings",
    "NP": "network primary device",
    "NW": "network settings",
    "NR": "network reset",
    "WA": "wireless antenna",
    "WE": "wireless encryption",
    "WI": "wireless settings",
    "WP": "wireless port",
    "WR": "wireless retry",
    "WS": "wireless settings",
}

# Groups of settings whose source (label or printer) is configurable per printer.
SETTING_GROUPS: dict[str, tuple[str, frozenset[str]]] = {
    "media": ("Media tracking and maximum length", frozenset({"MN", "ML"})),
    # Thermal transfer needs a ribbon: ^MTT from a label made for another printer stops a
    # direct thermal printer (or one used without ribbon) with "Ribbon out".
    "print_method": ("Print method (direct thermal or thermal transfer)", frozenset({"MT"})),
    "darkness_speed": ("Darkness and print speed", frozenset({"SD", "MD", "PR"})),
    "position": ("Label position and orientation", frozenset({"LT", "LS", "TA", "PO"})),
    "print_mode": (
        "Print mode (tear-off, peel, cutter) and backfeed",
        frozenset({"MM", "JS", "XB"}),
    ),
}
Source = Literal["label", "printer"]
DEFAULT_POLICY: dict[str, Source] = {
    "media": "label",
    "print_method": "printer",
    "darkness_speed": "label",
    "position": "label",
    "print_mode": "printer",
}
_GROUP_OF = {code: group for group, (_, codes) in SETTING_GROUPS.items() for code in codes}


def resolve_policy(policy: Mapping[str, str] | None) -> dict[str, Source]:
    """Defaults merged with a printer's stored choices (unknown keys are ignored)."""
    merged = dict(DEFAULT_POLICY)
    for group, source in (policy or {}).items():
        if group in merged and source in ("label", "printer"):
            merged[group] = source  # type: ignore[assignment]
    return merged


_SGD_LINE = re.compile(r"(?im)^[ \t]*![ \t]*U1?\b.*(?:\r?\n|$)")
_EMPTY_FORMAT = re.compile(r"\^XA\s*\^XZ[ \t]*(?:\r?\n)?", re.IGNORECASE)
_BLANK_LINE = re.compile(r"(?m)^[ \t]*\r?\n")


@dataclass(slots=True)
class EmbeddedSetting:
    command: str
    description: str
    group: str | None  # None: always removed


@dataclass(slots=True)
class StripResult:
    zpl: str
    removed: list[EmbeddedSetting] = field(default_factory=list)
    kept: list[EmbeddedSetting] = field(default_factory=list)


def strip_printer_settings(zpl: str, policy: Mapping[str, str] | None = None) -> StripResult:
    """Remove the printer settings that should come from the printer, per `policy`."""
    sources = resolve_policy(policy)
    removed: list[EmbeddedSetting] = []
    kept: list[EmbeddedSetting] = []
    parts: list[str] = []
    last = 0
    for command in tokenize(zpl):
        description = PRINTER_SETTINGS.get(command.code)
        if description is None or command.end <= command.start:
            continue
        group = _GROUP_OF.get(command.code)
        setting = EmbeddedSetting(zpl[command.start : command.end].strip(), description, group)
        if group is not None and sources[group] == "label":
            kept.append(setting)
            continue
        removed.append(setting)
        parts.append(zpl[last : command.start])
        last = command.end
    parts.append(zpl[last:])
    result = "".join(parts)
    for match in _SGD_LINE.finditer(result):
        removed.append(EmbeddedSetting(match.group(0).strip(), "SGD printer setting", None))
    if not removed:
        return StripResult(zpl, kept=kept)
    result = _SGD_LINE.sub("", result)
    # Formats that held only settings are now empty; lines that held only settings are blank.
    result = _EMPTY_FORMAT.sub("", result)
    result = _BLANK_LINE.sub("", result)
    return StripResult(result, removed, kept)
