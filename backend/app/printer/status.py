"""Parsers for the printer's ~HS (host status) and ~HI (host identification) responses."""

from dataclasses import asdict, dataclass

STX = "\x02"
ETX = "\x03"

PRINT_MODES = {
    "0": "rewind",
    "1": "peel",
    "2": "tear",
    "3": "cutter",
    "4": "applicator",
    "5": "delayed_cut",
    "6": "linerless_peel",
    "7": "linerless_rewind",
    "8": "partial_cutter",
    "9": "rfid",
    "K": "kiosk",
}

DPMM_TO_DPI = {6: 152, 8: 203, 12: 300, 24: 600}


class StatusParseError(ValueError):
    pass


@dataclass(slots=True)
class PrinterStatus:
    paper_out: bool
    paused: bool
    label_length: int
    formats_in_buffer: int
    buffer_full: bool
    corrupt_ram: bool
    under_temperature: bool
    over_temperature: bool
    head_open: bool
    ribbon_out: bool
    thermal_transfer: bool
    print_mode: str
    labels_remaining: int
    graphics_stored: int

    @property
    def ready(self) -> bool:
        return not self.problems

    @property
    def problems(self) -> list[str]:
        problems = []
        if self.paper_out:
            problems.append("Paper out")
        if self.head_open:
            problems.append("Head open")
        if self.ribbon_out and self.thermal_transfer:
            problems.append("Ribbon out")
        if self.paused:
            problems.append("Paused")
        if self.buffer_full:
            problems.append("Receive buffer full")
        if self.corrupt_ram:
            problems.append("Corrupt RAM")
        if self.under_temperature:
            problems.append("Under temperature")
        if self.over_temperature:
            problems.append("Over temperature")
        return problems

    @property
    def blocking_problems(self) -> list[str]:
        """Problems that make printing impossible (a paused printer still buffers jobs)."""
        return [p for p in self.problems if p != "Paused"]

    def to_dict(self) -> dict:
        return asdict(self) | {"ready": self.ready, "problems": self.problems}


def _frames(raw: str) -> list[list[str]]:
    frames = []
    for chunk in raw.split(STX)[1:]:
        body = chunk.split(ETX, 1)[0]
        frames.append([field.strip() for field in body.split(",")])
    return frames


def _flag(fields: list[str], index: int) -> bool:
    return index < len(fields) and fields[index] == "1"


def _int(fields: list[str], index: int) -> int:
    try:
        return int(fields[index])
    except IndexError, ValueError:
        return 0


def parse_host_status(raw: bytes | str) -> PrinterStatus:
    text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
    frames = _frames(text)
    if len(frames) < 2 or len(frames[0]) < 12 or len(frames[1]) < 9:
        raise StatusParseError(f"Unexpected ~HS response: {text!r}")
    s1, s2 = frames[0], frames[1]
    return PrinterStatus(
        paper_out=_flag(s1, 1),
        paused=_flag(s1, 2),
        label_length=_int(s1, 3),
        formats_in_buffer=_int(s1, 4),
        buffer_full=_flag(s1, 5),
        corrupt_ram=_flag(s1, 9),
        under_temperature=_flag(s1, 10),
        over_temperature=_flag(s1, 11),
        head_open=_flag(s2, 2),
        ribbon_out=_flag(s2, 3),
        thermal_transfer=_flag(s2, 4),
        print_mode=PRINT_MODES.get(s2[5], s2[5]),
        labels_remaining=_int(s2, 8),
        graphics_stored=_int(s2, 10),
    )


@dataclass(slots=True)
class HostIdentification:
    model: str
    firmware: str
    dpmm: int
    dpi: int
    memory: str


def parse_host_identification(raw: bytes | str) -> HostIdentification:
    text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
    frames = _frames(text)
    if not frames or len(frames[0]) < 3:
        raise StatusParseError(f"Unexpected ~HI response: {text!r}")
    fields = frames[0]
    dpmm = _int(fields, 2)
    return HostIdentification(
        model=fields[0],
        firmware=fields[1],
        dpmm=dpmm,
        dpi=DPMM_TO_DPI.get(dpmm, round(dpmm * 25.4)),
        memory=fields[3] if len(fields) > 3 else "",
    )
