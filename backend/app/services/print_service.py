"""Resolving label content and sending print jobs."""

import time
from collections.abc import Iterable, Mapping
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import User
from app.config import Settings
from app.models import Label, Printer, PrintJob
from app.printer.client import PrinterClient, PrinterError
from app.render.lexer import Command, tokenize
from app.render.renderer import PRINTING
from app.zpl.generator import Design, design_variables, generate_zpl
from app.zpl.printer_settings import strip_printer_settings
from app.zpl.templating import (
    TemplateError,
    VariableDef,
    extract_variables,
    field_variables,
    merge_variable_defs,
    resolve_values,
    substitute_zpl,
)

# A format prints if it has printing commands (same set the renderer uses) or recalls a stored
# format; formats that only store one (^DF) never print.
_PRINTS = PRINTING | {"XF"}
_SERIALIZED = {"SN", "SF"}


def reject_nul(*texts: str | None) -> None:
    """Postgres cannot store NUL characters; refuse them before anything is printed, because
    the job is recorded only after printing and a failed insert would lose it."""
    if any(text and "\x00" in text for text in texts):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Text must not contain NUL (\\x00) characters"
        )


def printer_client(printer: Printer, settings: Settings) -> PrinterClient:
    return PrinterClient(
        printer.host,
        printer.port,
        timeout=settings.printer_timeout,
        settings_idle=settings.printer_settings_idle,
        policy=settings.printer_address_policy,
    )


def _formats(commands: list[Command]) -> list[list[Command]]:
    formats: list[list[Command]] = []
    current: list[Command] | None = None
    for command in commands:
        if command.code == "XA":
            current = [command]
        elif current is not None:
            current.append(command)
            if command.code == "XZ":
                formats.append(current)
                current = None
    return formats


def _count(value: str, default: int) -> int:
    value = value.strip()
    # ASCII digits only: str.isdigit() accepts characters like "²" that int() rejects.
    return int(value) if value.isascii() and value.isdigit() else default


def apply_copies(zpl: str, copies: int) -> str:
    """Print `copies` of every label by multiplying its ^PQ quantity.

    Setup-only formats (like the settings block ZebraDesigner emits, often with ^JUS) are left
    alone so they are sent once instead of once per copy. The commands are found with the ZPL
    tokenizer, so ^PQ inside field data or a comment is not touched and changed control
    characters (^CC) are honoured; the last ^PQ of a format is the one the printer uses.
    """
    if copies <= 1:
        return zpl
    printable = [
        fmt
        for fmt in _formats(tokenize(zpl))
        if any(c.code in _PRINTS for c in fmt) and not any(c.code == "DF" for c in fmt)
    ]
    if not printable:
        separator = "" if zpl.endswith("\n") else "\n"
        return separator.join([zpl] * copies)
    edits: list[tuple[int, int, str]] = []
    for fmt in printable:
        quantity = next((c for c in reversed(fmt) if c.code == "PQ"), None)
        if quantity is None:
            end = fmt[-1]  # ^XZ, written with whatever caret the data uses
            edits.append((end.start, end.start, f"{zpl[end.start]}PQ{copies}"))
            continue
        original = zpl[quantity.start : quantity.end]
        trailing = original[len(original.rstrip()) :]
        args = quantity.args() + [""] * 3
        args[0] = str(_count(args[0], 1) * copies)
        if any(c.code in _SERIALIZED for c in fmt):
            # Each serial number is printed `copies` times instead of continuing the series:
            # r replicates per serial number (^PQq,p,r,o, p.244).
            args[2] = str((_count(args[2], 0) + 1) * copies - 1)
        params = quantity.delimiter.join(args).rstrip(quantity.delimiter)
        text = f"{zpl[quantity.start]}PQ{params}{trailing}"
        edits.append((quantity.start, quantity.end, text))
    parts, last = [], 0
    for start, end, text in edits:
        parts += [zpl[last:start], text]
        last = end
    parts.append(zpl[last:])
    return "".join(parts)


def label_variable_names(label: Label) -> list[str]:
    if label.kind == "design" and label.design:
        return design_variables(Design.model_validate(label.design))
    return extract_variables(label.zpl)


def label_definitions(label: Label) -> list[VariableDef]:
    return merge_variable_defs(label_variable_names(label), label.variables or [])


def label_field_variables(label: Label) -> set[str]:
    """Variables whose values may contain ^ and ~: a design escapes all of them."""
    if label.kind == "design" and label.design:
        return set(label_variable_names(label))
    return field_variables(label.zpl)


def render_label(label: Label, values: Mapping[str, str], *, now: datetime | None = None) -> str:
    if label.kind == "design" and label.design:
        return generate_zpl(Design.model_validate(label.design), values, now=now)
    return substitute_zpl(label.zpl, values, now=now)


def resolve_label(
    label: Label, provided: Mapping[str, str] | None, *, strict: bool = True
) -> tuple[str, dict[str, str]]:
    definitions = label_definitions(label)
    values = resolve_values(
        [d.name for d in definitions],
        definitions,
        provided,
        strict=strict,
        field_only=label_field_variables(label),
    )
    return render_label(label, values), values


def resolve_zpl(
    zpl: str,
    provided: Mapping[str, str] | None,
    definitions: Iterable[VariableDef] = (),
    *,
    strict: bool = True,
):
    names, field_only = extract_variables(zpl), field_variables(zpl)
    values = resolve_values(names, definitions, provided, strict=strict, field_only=field_only)
    return substitute_zpl(zpl, values), values


def resolve_design(
    design: Design,
    provided: Mapping[str, str] | None,
    definitions: Iterable[VariableDef] = (),
    *,
    strict: bool = True,
):
    names = design_variables(design)
    values = resolve_values(names, definitions, provided, strict=strict, field_only=names)
    return generate_zpl(design, values), values


def design_dpi(label: Label | None = None, design: Design | None = None) -> int | None:
    """Resolution a design was made for; None for ZPL, whose stored dpi is only informative."""
    if design is not None:
        return design.dpi
    if label is not None and label.kind == "design" and label.design:
        return Design.model_validate(label.design).dpi
    return None


def check_resolution(printer: Printer, label: Label | None = None, design: Design | None = None):
    """Refuse to print a design on a printer with another resolution.

    Designs are laid out in printer dots, so a 203 dpi design printed at 300 dpi comes out
    at two thirds of its size.
    """
    dpi = design_dpi(label, design)
    if dpi is not None and dpi != printer.dpi:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The label is designed for {dpi} dpi but {printer.name} prints at {printer.dpi} "
            "dpi; choose another printer, or change the resolution in the designer (which "
            "rescales the design)",
        )


def check_reprint_resolution(printer: Printer, job_dpi: int) -> None:
    """Refuse to reprint a job on a printer with another resolution: its ZPL is in the dots
    of the printer it was made for."""
    if job_dpi != printer.dpi:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The job was printed at {job_dpi} dpi but {printer.name} prints at {printer.dpi} "
            "dpi; reprint it on a printer with the same resolution",
        )


def template_http_error(exc: TemplateError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"message": str(exc), "missing": exc.missing, "invalid": exc.invalid},
    )


async def get_printer(session: AsyncSession, printer_id: int | None) -> Printer:
    if printer_id is not None:
        printer = await session.get(Printer, printer_id)
    else:
        printer = await session.scalar(
            select(Printer).order_by(Printer.is_default.desc(), Printer.id).limit(1)
        )
    if printer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    return printer


async def printer_policy(session: AsyncSession, printer_id: int | None) -> dict[str, str] | None:
    """Label-settings policy of the given printer, or of the default printer."""
    try:
        printer = await get_printer(session, printer_id)
    except HTTPException:
        return None
    return printer.label_settings


async def send_job(
    session: AsyncSession,
    settings: Settings,
    printer: Printer,
    zpl: str,
    *,
    copies: int,
    source: str,
    user: User,
    label: Label | None = None,
    label_name: str | None = None,
    values: Mapping[str, str] | None = None,
    keep_printer_settings: bool = False,
    api_token_id: int | None = None,
    idempotency_key: str | None = None,
    idempotency_hash: str | None = None,
) -> PrintJob:
    reject_nul(zpl, label_name, *(values or {}), *(values or {}).values())
    if not keep_printer_settings:
        # The printer's own configuration wins over settings embedded in the label.
        stripped = await run_in_threadpool(strip_printer_settings, zpl, printer.label_settings)
        zpl = stripped.zpl
    started = time.monotonic()
    error = None
    maybe_sent = False
    try:
        payload = await run_in_threadpool(apply_copies, zpl, copies)
        await printer_client(printer, settings).send(payload)
    except PrinterError as exc:
        error = str(exc)
        maybe_sent = exc.maybe_sent
    # A sent job claims its Idempotency-Key. So does a failure after the data left for the
    # printer, since that label may still come out: retrying it blindly could print it twice.
    # A failure before anything was sent leaves the key free so the retry really prints.
    claims_key = not error or maybe_sent
    job = PrintJob(
        printer_id=printer.id,
        printer_name=printer.name,
        printer_host=f"{printer.host}:{printer.port}",
        dpi=printer.dpi,
        label_id=label.id if label else None,
        label_name=label.name if label else label_name,
        source=source,
        zpl=zpl,
        variables=dict(values or {}),
        copies=copies,
        status="failed" if error else "sent",
        error=error,
        duration_ms=round((time.monotonic() - started) * 1000),
        created_by=user.identity,
        api_token_id=api_token_id,
        idempotency_key=idempotency_key if claims_key else None,
        idempotency_hash=idempotency_hash if claims_key else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
