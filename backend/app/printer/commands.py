"""Printer settings model and translation to ZPL commands."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.printer.sgd import SgdValue

MediaTracking = Literal["continuous", "gap", "mark", "variable"]
PrintMethod = Literal["direct", "transfer"]
PrintMode = Literal["tear", "peel", "rewind", "cutter", "applicator", "delayed_cut", "kiosk"]
Orientation = Literal["normal", "inverted"]

_TRACKING_ZPL = {"continuous": "N", "gap": "Y", "mark": "M", "variable": "V"}
_METHOD_ZPL = {"direct": "D", "transfer": "T"}
_MODE_ZPL = {
    "tear": "T",
    "peel": "P",
    "rewind": "R",
    "cutter": "C",
    "applicator": "A",
    "delayed_cut": "D",
    "kiosk": "K",
}
_ORIENTATION_ZPL = {"normal": "N", "inverted": "I"}


class PrinterSettings(BaseModel):
    """Settings that can be changed from the UI. All fields optional on update."""

    print_width: int | None = Field(None, ge=2, le=1344, description="Print width in dots (^PW)")
    label_length: int | None = Field(None, ge=1, le=32000, description="Label length in dots (^LL)")
    darkness: int | None = Field(None, ge=0, le=30, description="Darkness 0-30 (~SD)")
    speed: int | None = Field(None, ge=1, le=14, description="Print speed in ips (^PR)")
    media_tracking: MediaTracking | None = None
    print_method: PrintMethod | None = None
    print_mode: PrintMode | None = None
    tear_off: int | None = Field(None, ge=-120, le=120, description="Tear-off adjust (~TA)")
    label_top: int | None = Field(None, ge=-120, le=120, description="Label top (^LT)")
    label_shift: int | None = Field(None, ge=-9999, le=9999, description="Label shift (^LS)")
    orientation: Orientation | None = None


def settings_to_zpl(settings: PrinterSettings, *, save: bool = True) -> str:
    """Build the command string that applies (and optionally persists) the settings."""
    tilde: list[str] = []
    body: list[str] = []
    if settings.darkness is not None:
        tilde.append(f"~SD{settings.darkness:02d}")
    if settings.tear_off is not None:
        value = settings.tear_off
        tilde.append(f"~TA{value:03d}" if value >= 0 else f"~TA-{-value:03d}")
    if settings.print_width is not None:
        body.append(f"^PW{settings.print_width}")
    if settings.label_length is not None:
        body.append(f"^LL{settings.label_length}")
    if settings.speed is not None:
        body.append(f"^PR{settings.speed}")
    if settings.media_tracking is not None:
        body.append(f"^MN{_TRACKING_ZPL[settings.media_tracking]}")
    if settings.print_method is not None:
        body.append(f"^MT{_METHOD_ZPL[settings.print_method]}")
    if settings.print_mode is not None:
        body.append(f"^MM{_MODE_ZPL[settings.print_mode]}")
    if settings.label_top is not None:
        body.append(f"^LT{settings.label_top}")
    if settings.label_shift is not None:
        body.append(f"^LS{settings.label_shift}")
    if settings.orientation is not None:
        body.append(f"^PO{_ORIENTATION_ZPL[settings.orientation]}")
    if save:
        body.append("^JUS")
    lines = [*tilde]
    if body:
        lines.append("^XA" + "".join(body) + "^XZ")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SettingDef:
    name: str
    label: str
    sgd_keys: tuple[str, ...]


# Curated settings shown in the UI, with the SGD keys used to read their current value.
SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef("print_width", "Print width", ("ezpl.print_width",)),
    SettingDef("label_length", "Label length", ("zpl.label_length", "ezpl.label_length")),
    SettingDef("darkness", "Darkness", ("print.tone",)),
    SettingDef("speed", "Print speed", ("media.speed",)),
    SettingDef("media_tracking", "Media tracking", ("ezpl.media_type", "media.type")),
    SettingDef("print_method", "Print method", ("ezpl.print_method",)),
    SettingDef("print_mode", "Print mode", ("media.printmode", "ezpl.print_mode")),
    SettingDef("tear_off", "Tear-off adjust", ("ezpl.tear_off",)),
    SettingDef("label_top", "Label top", ("zpl.label_top",)),
    SettingDef("label_shift", "Label shift", ("zpl.left_position", "zpl.label_shift")),
    SettingDef("orientation", "Print orientation", ("zpl.print_orientation",)),
)

INFO_KEYS: dict[str, tuple[str, ...]] = {
    "friendly_name": ("device.friendly_name",),
    "firmware": ("appl.name",),
    "serial": ("device.unique_id",),
    "odometer": ("odometer.total_print_length", "odometer.media_marker_count"),
    "head_resolution": ("head.resolution.in_dpi",),
    # Wired first: on a cabled printer ip.addr can belong to an unused interface.
    "ip_address": ("internal_wired.ip.addr", "wlan.ip.addr", "ip.addr"),
    "mac_address": ("internal_wired.mac_addr", "wlan.mac_addr"),
}


_UNSET = {"", "0.0.0.0", "00:00:00:00:00:00"}


def _first(values: dict[str, SgdValue], keys: tuple[str, ...]) -> SgdValue | None:
    """The first of `keys` the printer reports with a real value."""
    for key in keys:
        if key in values and values[key].value.strip() not in _UNSET:
            return values[key]
    return None


def curated_settings(values: dict[str, SgdValue]) -> list[dict]:
    result = []
    for definition in SETTING_DEFS:
        found = _first(values, definition.sgd_keys)
        result.append(
            {
                "name": definition.name,
                "label": definition.label,
                "value": found.value if found else None,
                "choices": found.choices if found else None,
            }
        )
    return result


def device_info(values: dict[str, SgdValue]) -> dict[str, str | None]:
    info = {}
    for name, keys in INFO_KEYS.items():
        found = _first(values, keys)
        info[name] = found.value if found else None
    return info


ACTIONS: dict[str, tuple[str, str]] = {
    "calibrate": ("~JC", "Calibrate media and ribbon sensors"),
    "config_label": ("~WC", "Print configuration label"),
    "network_label": ("~WL", "Print network configuration label"),
    "sensor_profile": ("~JG", "Print sensor profile"),
    "feed": ("^XA^PH^XZ", "Feed one label"),
    "cancel_all": ("~JA", "Cancel all queued jobs"),
    "reset": ('! U1 do "device.reset" ""\r\n', "Reset (reboot) the printer"),
    "factory_defaults": ("^XA^JUF^XZ", "Restore factory defaults"),
}
