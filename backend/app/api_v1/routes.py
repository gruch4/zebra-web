import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer
from starlette.concurrency import run_in_threadpool

from app.api.deps import SessionDep, SettingsDep
from app.api.labels import apply_content, get_label, search_labels
from app.api_v1.auth import ApiClient, ClientDep, current_client
from app.api_v1.schemas import (
    ApiLabel,
    ApiLabelPage,
    ApiPrinter,
    ApiPrintJob,
    PrintLabelRequest,
    PrintZplRequest,
    StoreLabelRequest,
    Text,
)
from app.config import Settings
from app.models import Label, Printer, PrintJob
from app.services.print_service import (
    check_resolution,
    get_printer,
    resolve_label,
    resolve_zpl,
    send_job,
    template_http_error,
)
from app.zpl.templating import BUILTINS, TemplateError

router = APIRouter(
    dependencies=[Depends(current_client)],
    responses={401: {"description": "The API token is missing, invalid, expired or revoked."}},
)

API_TAG = "api"
DEFAULT_DPI = 203

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[!-~]+$",
        description=(
            "Makes a print request safe to retry. If a request with the same key from the same "
            "token was already printed, that job is returned (header `Idempotent-Replay: true`) "
            "and nothing is printed again. If the printer could not be reached at all, the key "
            "stays free and a retry prints. If the failure came after the data was sent "
            "(`error` says the printer may still print it), the key is kept and the same key "
            "returns that failed job again: check the printer, and use a new key to print "
            "again. Reusing a key for a different request is a `409`."
        ),
    ),
]

PRINT_RESPONSES = {
    502: {"model": ApiPrintJob, "description": "The printer failed; the failed job is returned."},
    404: {"description": "The printer (or label) does not exist."},
    409: {
        "description": (
            "The `Idempotency-Key` was already used for a different request, or a request with "
            "it is still being processed (retry after the `Retry-After` seconds)."
        )
    },
    422: {
        "description": (
            "Invalid request, or `{{variables}}` are missing, invalid or built in (`date`, "
            "`time`, `datetime`, `year`). For template errors `detail` is "
            "`{message, missing, invalid}`."
        )
    },
}


def fingerprint(kind: str, **parts: object) -> str:
    """Identifies a print request, to tell a retry from a different request with the same key."""
    payload = json.dumps([kind, parts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def lock_key(token_id: int, key: str) -> int:
    digest = hashlib.sha256(f"{token_id}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def lock_wait(settings: Settings) -> float:
    """How long a duplicate waits for the request that is printing its key: about as long as
    that request can take against an unreachable printer (connect + send timeouts)."""
    return 2 * settings.printer_timeout + 2


LOCK_POLL = 0.1


async def find_replay(
    session: SessionDep,
    settings: Settings,
    client: ApiClient,
    key: str | None,
    request_hash: str,
) -> PrintJob | None:
    """The job that already claimed this key, or None. Duplicates of a request that is still
    printing wait for it, but only for a bounded time and without holding a connection."""
    if key is None:
        return None
    params = {"key": lock_key(client.token_id, key)}
    deadline = time.monotonic() + lock_wait(settings)
    # The lock lasts until the transaction ends (send_job commits), so a duplicate that arrives
    # while the first request is still printing cannot print a second time.
    while not await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), params):
        await session.rollback()  # give the connection back instead of idling on it
        if time.monotonic() >= deadline:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A request with this Idempotency-Key is still being processed; retry shortly",
                headers={"Retry-After": "5"},
            )
        await asyncio.sleep(LOCK_POLL)
    job = await session.scalar(
        select(PrintJob).where(
            PrintJob.api_token_id == client.token_id, PrintJob.idempotency_key == key
        )
    )
    if job is not None and job.idempotency_hash != request_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This Idempotency-Key was already used for another request"
        )
    return job


def finish_print(response: Response, job: PrintJob, *, replay: bool = False) -> PrintJob:
    if replay:
        response.headers["Idempotent-Replay"] = "true"
    if job.status == "failed":
        response.status_code = status.HTTP_502_BAD_GATEWAY
    return job


def reject_builtin_variables(variables: Mapping[str, str]) -> None:
    """Built-in names are always filled from the clock; a value for one would be ignored."""
    reserved = {
        name: "is filled in automatically and cannot be set"
        for name in variables
        if name in BUILTINS
    }
    if reserved:
        raise template_http_error(TemplateError(invalid=reserved))


@router.get(
    "/printers",
    response_model=list[ApiPrinter],
    operation_id="listPrinters",
    tags=["Printers"],
    summary="List printers",
)
async def list_printers(session: SessionDep):
    """The printers you can print to. Use an `id` as `printer_id` in the print requests."""
    rows = await session.scalars(select(Printer).order_by(Printer.is_default.desc(), Printer.name))
    return rows.all()


@router.post(
    "/print",
    response_model=ApiPrintJob,
    operation_id="printZpl",
    tags=["Printing"],
    summary="Print ZPL",
    responses=PRINT_RESPONSES,
)
async def print_zpl(
    body: PrintZplRequest,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
    response: Response,
    idempotency_key: IdempotencyKey = None,
):
    """Send ZPL to a printer and record it in the print history (source `API`).

    The request returns once the printer has accepted the data, which can take several
    seconds. If the printer cannot be reached the job is still recorded, with status
    `failed`, and the response is `502` with that job in the body.
    """
    reject_builtin_variables(body.variables)
    request_hash = fingerprint(
        "zpl",
        zpl=body.zpl,
        name=body.name,
        variables=body.variables,
        copies=body.copies,
        printer_id=body.printer_id,
    )
    replay = await find_replay(session, settings, client, idempotency_key, request_hash)
    if replay is not None:
        return finish_print(response, replay, replay=True)
    printer = await get_printer(session, body.printer_id)
    try:
        zpl, values = await run_in_threadpool(resolve_zpl, body.zpl, body.variables)
    except TemplateError as exc:
        raise template_http_error(exc) from exc
    job = await send_job(
        session,
        settings,
        printer,
        zpl,
        copies=body.copies,
        source="api",
        user=client.as_user(),
        label_name=body.name,
        values=values,
        api_token_id=client.token_id,
        idempotency_key=idempotency_key,
        idempotency_hash=request_hash,
    )
    return finish_print(response, job)


def _fill_label(label: Label, body: StoreLabelRequest, client: ApiClient) -> None:
    """Apply a store request; on an existing label only the fields that were sent change."""
    sent = body.model_fields_set
    label.name = body.name
    if "description" in sent:
        label.description = body.description or ""
    tags = list(dict.fromkeys(body.tags or [])) if "tags" in sent else list(label.tags)
    label.tags = tags if API_TAG in tags else [*tags, API_TAG]
    for field in ("width_mm", "height_mm"):
        if field in sent:
            setattr(label, field, getattr(body, field))
    if "dpi" in sent:
        label.dpi = body.dpi or DEFAULT_DPI
    if body.external_ref:
        label.external_ref = body.external_ref
        label.external_owner = client.owner_sub
    apply_content(label, zpl=body.zpl)


async def _find_by_ref(session: SessionDep, client: ApiClient, ref: str) -> Label | None:
    return await session.scalar(
        select(Label).where(Label.external_owner == client.owner_sub, Label.external_ref == ref)
    )


@router.post(
    "/labels",
    response_model=ApiLabel,
    status_code=status.HTTP_201_CREATED,
    operation_id="storeLabel",
    tags=["Labels"],
    summary="Store a label",
    responses={200: {"model": ApiLabel, "description": "An existing label was updated."}},
)
async def store_label(
    body: StoreLabelRequest, session: SessionDep, client: ClientDep, response: Response
):
    """Save ZPL in the labels archive so it can be printed later, from the web UI or with
    `POST /labels/{label_id}/print`. Nothing is printed.

    With an `external_ref`, a label that already has that reference is **updated** (`200`)
    instead of creating a duplicate (`201`); fields you leave out keep their current value.
    """
    for attempt in range(2):
        label = None
        if body.external_ref:
            label = await _find_by_ref(session, client, body.external_ref)
        created = label is None
        if label is None:
            label = Label(
                kind="zpl",
                created_by=client.identity,
                variables=[],
                tags=[],
                description="",
                dpi=DEFAULT_DPI,
            )
            session.add(label)
        _fill_label(label, body, client)
        try:
            await session.commit()
        except IntegrityError:
            # Two requests with the same new external_ref raced; the loser updates instead.
            await session.rollback()
            if not body.external_ref or attempt == 1:
                raise
            continue
        break
    await session.refresh(label)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return label


@router.get(
    "/labels",
    response_model=ApiLabelPage,
    operation_id="listLabels",
    tags=["Labels"],
    summary="List labels",
)
async def list_labels(
    session: SessionDep,
    client: ClientDep,
    q: Annotated[Text | None, Query(description="Search in name and description.")] = None,
    tag: Annotated[Text | None, Query(description="Only labels with this tag.")] = None,
    external_ref: Annotated[
        Text | None, Query(description="Only the label you stored with this `external_ref`.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """All labels in the archive, including those made in the web UI, newest first, without
    their ZPL (get a single label for that)."""
    # The ZPL (up to megabytes per label) is left out of the list; GET /labels/{id} has it.
    stmt = search_labels(select(Label).options(defer(Label.zpl), defer(Label.design)), q, tag)
    if external_ref:
        stmt = stmt.where(
            Label.external_owner == client.owner_sub, Label.external_ref == external_ref
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    items = await session.scalars(
        stmt.order_by(Label.updated_at.desc(), Label.id.desc()).limit(limit).offset(offset)
    )
    return ApiLabelPage(items=items.all(), total=total or 0)


@router.get(
    "/labels/{label_id}",
    response_model=ApiLabel,
    operation_id="getLabel",
    tags=["Labels"],
    summary="Get a label",
    responses={404: {"description": "The label does not exist."}},
)
async def read_label(label_id: int, session: SessionDep):
    return await get_label(session, label_id)


@router.post(
    "/labels/{label_id}/print",
    response_model=ApiPrintJob,
    operation_id="printLabel",
    tags=["Printing"],
    summary="Print an archived label",
    responses=PRINT_RESPONSES,
)
async def print_label(
    label_id: int,
    body: PrintLabelRequest,
    session: SessionDep,
    settings: SettingsDep,
    client: ClientDep,
    response: Response,
    idempotency_key: IdempotencyKey = None,
):
    """Print a label from the archive, filling in its `{{variables}}`. Works for labels made
    in the web UI, in the designer or through `POST /labels`. Failure and retry behaviour is
    the same as for `POST /print`."""
    reject_builtin_variables(body.variables)
    request_hash = fingerprint(
        "label",
        label_id=label_id,
        variables=body.variables,
        copies=body.copies,
        printer_id=body.printer_id,
    )
    replay = await find_replay(session, settings, client, idempotency_key, request_hash)
    if replay is not None:
        return finish_print(response, replay, replay=True)
    label = await get_label(session, label_id)
    printer = await get_printer(session, body.printer_id)
    try:
        zpl, values = await run_in_threadpool(resolve_label, label, body.variables)
    except TemplateError as exc:
        raise template_http_error(exc) from exc
    check_resolution(printer, label)
    job = await send_job(
        session,
        settings,
        printer,
        zpl,
        copies=body.copies,
        source="api",
        user=client.as_user(),
        label=label,
        values=values,
        api_token_id=client.token_id,
        idempotency_key=idempotency_key,
        idempotency_hash=request_hash,
    )
    return finish_print(response, job)


@router.get(
    "/jobs/{job_id}",
    response_model=ApiPrintJob,
    operation_id="getJob",
    tags=["Printing"],
    summary="Get a print job",
    responses={404: {"description": "No such job made through the API."}},
)
async def read_job(job_id: int, session: SessionDep):
    """A print job made through the API (any token), e.g. to check its status."""
    job = await session.scalar(
        select(PrintJob).where(PrintJob.id == job_id, PrintJob.api_token_id.is_not(None))
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Print job not found")
    return job
