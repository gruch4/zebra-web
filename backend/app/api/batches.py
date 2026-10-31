from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep, SettingsDep, UserDep
from app.api.labels import get_label
from app.models import PrintBatch, PrintJob
from app.schemas import BatchOut, BatchRequest, DryRunOut, Page, ParsedRow, ParseResult
from app.services.batch_service import BatchRunner
from app.services.print_service import (
    apply_copies,
    check_resolution,
    get_printer,
    label_definitions,
    label_field_variables,
    printer_policy,
    render_label,
)
from app.zpl.datasources import (
    DataFormat,
    DataSourceError,
    RowResult,
    auto_map,
    build_rows,
    copies_column,
    parse_data,
)
from app.zpl.printer_settings import strip_printer_settings

router = APIRouter(prefix="/batches", tags=["batches"])


def _runner(request: Request) -> BatchRunner:
    return request.app.state.batch_runner


def _parsed(rows) -> list[ParsedRow]:
    return [
        ParsedRow(index=r.index, values=r.values, copies=r.copies, errors=r.errors) for r in rows
    ]


@router.post("/parse", response_model=ParseResult)
async def parse_batch_data(
    session: SessionDep,
    settings: SettingsDep,
    label_id: Annotated[int, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    format: Annotated[DataFormat | None, Form()] = None,
):
    label = await get_label(session, label_id)
    if file is not None:
        content = await file.read(settings.max_upload_bytes + 1)
        filename = file.filename
    elif text:
        content, filename = text.encode("utf-8"), None
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a file or paste data")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The data file is too large")
    try:
        table = parse_data(content, filename=filename, fmt=format, max_rows=settings.max_batch_rows)
    except DataSourceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    definitions = label_definitions(label)
    mapping = auto_map(table.columns, [d.name for d in definitions])
    copies_col = copies_column(table.columns)
    rows = build_rows(
        table.rows,
        definitions,
        mapping,
        copies_from=copies_col,
        field_only=label_field_variables(label),
    )
    errors = sum(1 for r in rows if not r.valid)
    return ParseResult(
        format=table.format,
        columns=table.columns,
        rows=table.rows,
        mapping=mapping,
        copies_column=copies_col,
        preview=_parsed(rows),
        valid_count=len(rows) - errors,
        error_count=errors,
    )


@router.post("/validate", response_model=list[ParsedRow])
async def validate_batch(body: BatchRequest, session: SessionDep):
    label = await get_label(session, body.label_id)
    return _parsed(_build(body, label))


def _build(body: BatchRequest, label) -> list[RowResult]:
    """Validate rows; variables missing from the mapping are matched to columns by name."""
    definitions = label_definitions(label)
    columns = list(dict.fromkeys(key for row in body.rows for key in row))
    mapping = auto_map(columns, [d.name for d in definitions]) | body.mapping
    return build_rows(
        body.rows,
        definitions,
        mapping,
        body.constants,
        copies_from=body.copies_column,
        field_only=label_field_variables(label),
    )


def _select_rows(body: BatchRequest, label) -> tuple[list[RowResult], list[RowResult]]:
    rows = _build(body, label)
    selected = set(body.selected) if body.selected is not None else None
    chosen = [r for r in rows if selected is None or r.index in selected]
    printable = [r for r in chosen if r.valid]
    if not printable:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No valid rows to print")
    return printable, [r for r in chosen if not r.valid]


@router.post("/dry-run", response_model=DryRunOut)
async def dry_run_batch(body: BatchRequest, session: SessionDep):
    """Return the ZPL the batch would send, without printing."""
    label = await get_label(session, body.label_id)
    printable, skipped = _select_rows(body, label)
    # Same processing as the real batch: the printer replaces some embedded settings.
    policy = await printer_policy(session, body.printer_id)
    zpl = await run_in_threadpool(
        lambda: "".join(
            apply_copies(
                strip_printer_settings(render_label(label, r.values), policy).zpl, r.copies
            )
            for r in printable
        )
    )
    return DryRunOut(zpl=zpl, count=len(printable), skipped=_parsed(skipped))


@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(
    body: BatchRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    user: UserDep,
):
    if len(body.rows) > settings.max_batch_rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Too many rows")
    label = await get_label(session, body.label_id)
    printable, _ = _select_rows(body, label)
    printer = await get_printer(session, body.printer_id)
    check_resolution(printer, label)
    batch = PrintBatch(
        label_id=label.id,
        label_name=label.name,
        printer_id=printer.id,
        printer_name=printer.name,
        data_filename=body.data_filename,
        rows=[{"row": r.index, "values": r.values, "copies": r.copies} for r in printable],
        total=len(printable),
        status="queued",
        created_by=user.identity,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    _runner(request).start(batch.id)
    return batch


@router.get("", response_model=Page[BatchOut])
async def list_batches(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    total = await session.scalar(select(func.count(PrintBatch.id)))
    items = await session.scalars(
        select(PrintBatch).order_by(PrintBatch.created_at.desc()).limit(limit).offset(offset)
    )
    return Page(items=items.all(), total=total or 0)


async def _get_batch(session: SessionDep, batch_id: int) -> PrintBatch:
    batch = await session.get(PrintBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return batch


@router.get("/{batch_id}", response_model=BatchOut)
async def read_batch(batch_id: int, session: SessionDep):
    return await _get_batch(session, batch_id)


@router.post("/{batch_id}/cancel", response_model=BatchOut)
async def cancel_batch(batch_id: int, request: Request, session: SessionDep):
    batch = await _get_batch(session, batch_id)
    runner = _runner(request)
    if runner.is_running(batch_id):
        runner.cancel(batch_id)
        await runner.wait(batch_id)
        await session.refresh(batch)
    elif batch.status in ("queued", "running"):
        batch.status = "cancelled"
        await session.commit()
    return batch


@router.post("/{batch_id}/retry-failed", response_model=BatchOut, status_code=201)
async def retry_failed(batch_id: int, request: Request, session: SessionDep, user: UserDep):
    batch = await _get_batch(session, batch_id)
    if _runner(request).is_running(batch_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "The batch is still printing")
    sent_rows = set(
        (
            await session.scalars(
                select(PrintJob.batch_row).where(
                    PrintJob.batch_id == batch_id, PrintJob.status == "sent"
                )
            )
        ).all()
    )
    remaining = [row for row in batch.rows if row["row"] not in sent_rows]
    if not remaining:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to retry")
    if batch.label_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The label of this batch was deleted")
    if batch.printer_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The printer of this batch was deleted")
    printer = await get_printer(session, batch.printer_id)
    retry = PrintBatch(
        label_id=batch.label_id,
        label_name=batch.label_name,
        printer_id=printer.id,
        printer_name=printer.name,
        data_filename=f"Retry of batch #{batch.id}",
        rows=remaining,
        total=len(remaining),
        status="queued",
        created_by=user.identity,
    )
    session.add(retry)
    await session.commit()
    await session.refresh(retry)
    _runner(request).start(retry.id)
    return retry
