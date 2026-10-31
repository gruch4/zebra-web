from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, String, func, literal, or_, select, union_all
from starlette.concurrency import run_in_threadpool

from app.api.deps import PNG_RESPONSE, SessionDep, SettingsDep, UserDep, png_response
from app.api.labels import apply_content
from app.models import Label, PrintBatch, PrintJob
from app.render.renderer import render_cache
from app.schemas import BatchOut, JobSource, LabelOut, NoNulStr, Page, PrintJobOut, StoredIn
from app.services.print_service import check_reprint_resolution, get_printer, send_job

router = APIRouter(tags=["history"])


class ReprintRequest(BaseModel):
    printer_id: int | None = None
    copies: int | None = Field(None, ge=1, le=1000)


class SaveAsLabelRequest(StoredIn):
    name: str | None = Field(None, min_length=1, max_length=200)


class HistoryItem(BaseModel):
    kind: Literal["job", "batch"]
    created_at: datetime
    job: PrintJobOut | None = None
    batch: BatchOut | None = None


def _job_filters(
    stmt: Select,
    *,
    printer_id: int | None,
    status_: str | None,
    source: str | None,
    label_id: int | None,
    batch_id: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
    q: str | None,
) -> Select:
    if printer_id is not None:
        stmt = stmt.where(PrintJob.printer_id == printer_id)
    if status_:
        stmt = stmt.where(PrintJob.status == status_)
    if source:
        stmt = stmt.where(PrintJob.source == source)
    if label_id is not None:
        stmt = stmt.where(PrintJob.label_id == label_id)
    if batch_id is not None:
        stmt = stmt.where(PrintJob.batch_id == batch_id)
    if date_from:
        stmt = stmt.where(PrintJob.created_at >= date_from)
    if date_to:
        stmt = stmt.where(PrintJob.created_at <= date_to)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(PrintJob.label_name.ilike(pattern), PrintJob.zpl.ilike(pattern)))
    return stmt


@router.get("/jobs", response_model=Page[PrintJobOut])
async def list_jobs(
    session: SessionDep,
    printer_id: int | None = None,
    status_: Annotated[Literal["sent", "failed"] | None, Query(alias="status")] = None,
    source: JobSource | None = None,
    label_id: int | None = None,
    batch_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: NoNulStr | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = _job_filters(
        select(PrintJob),
        printer_id=printer_id,
        status_=status_,
        source=source,
        label_id=label_id,
        batch_id=batch_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
    )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    order = (
        (PrintJob.batch_row, PrintJob.id)
        if batch_id
        else (PrintJob.created_at.desc(), PrintJob.id.desc())
    )
    items = await session.scalars(stmt.order_by(*order).limit(limit).offset(offset))
    return Page(items=items.all(), total=total or 0)


@router.get("/history", response_model=Page[HistoryItem])
async def history(
    session: SessionDep,
    printer_id: int | None = None,
    status_: Annotated[Literal["sent", "failed"] | None, Query(alias="status")] = None,
    source: JobSource | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: NoNulStr | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Single jobs and batches (one row per batch) in one timeline."""
    parts = []
    if source != "batch":
        jobs = select(
            literal("job", String).label("kind"),
            PrintJob.id.label("id"),
            PrintJob.created_at.label("created_at"),
        ).where(PrintJob.batch_id.is_(None))
        jobs = _job_filters(
            jobs,
            printer_id=printer_id,
            status_=status_,
            source=source,
            label_id=None,
            batch_id=None,
            date_from=date_from,
            date_to=date_to,
            q=q,
        )
        parts.append(jobs)
    if source in (None, "batch"):
        batches = select(
            literal("batch", String).label("kind"),
            PrintBatch.id.label("id"),
            PrintBatch.created_at.label("created_at"),
        )
        if printer_id is not None:
            batches = batches.where(PrintBatch.printer_id == printer_id)
        if status_ == "failed":
            batches = batches.where(or_(PrintBatch.failed > 0, PrintBatch.status == "failed"))
        elif status_ == "sent":
            batches = batches.where(PrintBatch.sent > 0)
        if date_from:
            batches = batches.where(PrintBatch.created_at >= date_from)
        if date_to:
            batches = batches.where(PrintBatch.created_at <= date_to)
        if q:
            pattern = f"%{q}%"
            batches = batches.where(
                or_(PrintBatch.label_name.ilike(pattern), PrintBatch.data_filename.ilike(pattern))
            )
        parts.append(batches)
    timeline = (union_all(*parts) if len(parts) > 1 else parts[0]).subquery()
    total = await session.scalar(select(func.count()).select_from(timeline))
    rows = (
        await session.execute(
            select(timeline.c.kind, timeline.c.id)
            .order_by(timeline.c.created_at.desc(), timeline.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    job_ids = [row.id for row in rows if row.kind == "job"]
    batch_ids = [row.id for row in rows if row.kind == "batch"]
    jobs_by_id = {
        j.id: j for j in (await session.scalars(select(PrintJob).where(PrintJob.id.in_(job_ids))))
    }
    batches_by_id = {
        b.id: b
        for b in (await session.scalars(select(PrintBatch).where(PrintBatch.id.in_(batch_ids))))
    }
    items = []
    for row in rows:
        if row.kind == "job":
            job = jobs_by_id[row.id]
            items.append(HistoryItem(kind="job", created_at=job.created_at, job=job))
        else:
            batch = batches_by_id[row.id]
            items.append(HistoryItem(kind="batch", created_at=batch.created_at, batch=batch))
    return Page(items=items, total=total or 0)


async def _get_job(session: SessionDep, job_id: int) -> PrintJob:
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Print job not found")
    return job


@router.get("/jobs/{job_id}", response_model=PrintJobOut)
async def read_job(job_id: int, session: SessionDep):
    return await _get_job(session, job_id)


@router.get("/jobs/{job_id}/preview.png", response_class=Response, responses=PNG_RESPONSE)
async def preview_job(job_id: int, session: SessionDep):
    job = await _get_job(session, job_id)
    result = await run_in_threadpool(lambda: render_cache.render(job.zpl, dpi=job.dpi, index=0))
    return png_response(result)


@router.post("/jobs/{job_id}/reprint", response_model=PrintJobOut)
async def reprint_job(
    job_id: int, body: ReprintRequest, session: SessionDep, settings: SettingsDep, user: UserDep
):
    job = await _get_job(session, job_id)
    printer = await get_printer(session, body.printer_id or job.printer_id)
    check_reprint_resolution(printer, job.dpi)
    label = await session.get(Label, job.label_id) if job.label_id else None
    return await send_job(
        session,
        settings,
        printer,
        job.zpl,
        copies=body.copies or job.copies,
        source="reprint",
        user=user,
        label=label,
        label_name=job.label_name,
        values=job.variables,
        # job.zpl is what was actually sent (already processed for printer settings).
        keep_printer_settings=True,
    )


@router.post(
    "/jobs/{job_id}/save-as-label", response_model=LabelOut, status_code=status.HTTP_201_CREATED
)
async def save_job_as_label(
    job_id: int, body: SaveAsLabelRequest, session: SessionDep, user: UserDep
):
    job = await _get_job(session, job_id)
    label = Label(
        name=body.name or job.label_name or f"Print job #{job.id}",
        kind="zpl",
        dpi=job.dpi,
        tags=["from-history"],
        created_by=user.identity,
        variables=[],
    )
    apply_content(label, zpl=job.zpl)
    session.add(label)
    await session.commit()
    await session.refresh(label)
    return label
