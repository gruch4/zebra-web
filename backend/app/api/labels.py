import csv
import io
import json
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

import yaml
from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from openpyxl import Workbook
from sqlalchemy import Select, func, or_, select
from starlette.concurrency import run_in_threadpool

from app.api.deps import PNG_RESPONSE, SessionDep, SettingsDep, UserDep, mm_to_dots, png_response
from app.models import Label
from app.render.renderer import render_cache
from app.schemas import (
    LabelIn,
    LabelOut,
    LabelSummary,
    LabelUpdate,
    NoNulStr,
    Page,
    TemplatePreviewRequest,
    VariableDefsIn,
)
from app.services.print_service import label_definitions, label_variable_names, resolve_label
from app.zpl.generator import Design, generate_zpl
from app.zpl.printer_settings import strip_printer_settings
from app.zpl.templating import VariableDef, merge_variable_defs

router = APIRouter(tags=["labels"])


def attachment(filename: str) -> str:
    """Content-Disposition for any filename; header values must be latin-1."""
    fallback = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


async def get_label(session: SessionDep, label_id: int) -> Label:
    label = await session.get(Label, label_id)
    if label is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Label not found")
    return label


def apply_content(
    label: Label,
    *,
    zpl: str | None = None,
    design: Design | None = None,
    variables: list[VariableDef] | None = None,
) -> None:
    """Set label content and re-derive its variables (keeping known metadata)."""
    if label.kind == "design":
        if design is not None:
            label.design = design.model_dump(mode="json")
            label.width_mm, label.height_mm, label.dpi = (
                design.width_mm,
                design.height_mm,
                design.dpi,
            )
        if label.design:
            label.zpl = generate_zpl(Design.model_validate(label.design))
    elif zpl is not None:
        label.zpl = zpl
    existing = variables if variables is not None else (label.variables or [])
    names = label_variable_names(label)
    label.variables = [d.model_dump() for d in merge_variable_defs(names, existing)]


def label_preview(label: Label, values: dict[str, str] | None = None):
    zpl, _ = resolve_label(label, values or {}, strict=False)
    zpl = strip_printer_settings(zpl).zpl  # preview what will be printed
    return render_cache.render(
        zpl,
        dpi=label.dpi,
        width=mm_to_dots(label.width_mm, label.dpi),
        height=mm_to_dots(label.height_mm, label.dpi),
        index=0,
    )


def search_labels(stmt: Select, q: str | None, tag: str | None) -> Select:
    """Narrow a label query by text (name or description) and tag."""
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Label.name.ilike(pattern), Label.description.ilike(pattern)))
    if tag:
        stmt = stmt.where(Label.tags.contains([tag]))
    return stmt


@router.get("/labels", response_model=Page[LabelSummary])
async def list_labels(
    session: SessionDep,
    q: NoNulStr | None = None,
    tag: NoNulStr | None = None,
    kind: Literal["zpl", "design"] | None = None,
    has_variables: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = search_labels(select(Label), q, tag)
    if kind:
        stmt = stmt.where(Label.kind == kind)
    if has_variables is not None:
        count = func.jsonb_array_length(Label.variables)
        stmt = stmt.where(count > 0 if has_variables else count == 0)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    items = await session.scalars(
        stmt.order_by(Label.updated_at.desc(), Label.id.desc()).limit(limit).offset(offset)
    )
    return Page(items=items.all(), total=total or 0)


@router.get("/labels/tags", response_model=list[str])
async def list_tags(session: SessionDep):
    rows = await session.scalars(select(func.jsonb_array_elements_text(Label.tags)).distinct())
    return sorted(rows.all())


@router.post("/labels", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
async def create_label(body: LabelIn, session: SessionDep, user: UserDep):
    label = Label(
        name=body.name,
        description=body.description,
        kind=body.kind,
        width_mm=body.width_mm,
        height_mm=body.height_mm,
        dpi=body.dpi,
        tags=body.tags,
        created_by=user.identity,
        variables=[],
    )
    apply_content(label, zpl=body.zpl, design=body.design, variables=body.variables)
    session.add(label)
    await session.commit()
    await session.refresh(label)
    return label


@router.post("/labels/import", response_model=list[LabelOut], status_code=status.HTTP_201_CREATED)
async def import_labels(
    files: Annotated[list[UploadFile], File()],
    session: SessionDep,
    settings: SettingsDep,
    user: UserDep,
):
    labels = []
    for upload in files:
        content = await upload.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"{upload.filename} is too large"
            )
        name = (upload.filename or "Imported label").rsplit(".", 1)[0][:200] or "Imported label"
        zpl = content.decode("utf-8", "replace")
        if "\x00" in name or "\x00" in zpl:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{upload.filename} must not contain NUL (\\x00) characters",
            )
        label = Label(
            name=name, kind="zpl", created_by=user.identity, tags=["imported"], variables=[]
        )
        apply_content(label, zpl=zpl)
        session.add(label)
        labels.append(label)
    await session.commit()
    for label in labels:
        await session.refresh(label)
    return labels


@router.get("/labels/{label_id}", response_model=LabelOut)
async def read_label(label_id: int, session: SessionDep):
    return await get_label(session, label_id)


@router.put("/labels/{label_id}", response_model=LabelOut)
async def update_label(label_id: int, body: LabelUpdate, session: SessionDep):
    label = await get_label(session, label_id)
    for key in ("name", "description", "tags", "width_mm", "height_mm", "dpi"):
        value = getattr(body, key)
        if value is not None:
            setattr(label, key, value)
    apply_content(label, zpl=body.zpl, design=body.design, variables=body.variables)
    await session.commit()
    await session.refresh(label)
    return label


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(label_id: int, session: SessionDep):
    await session.delete(await get_label(session, label_id))
    await session.commit()


@router.post(
    "/labels/{label_id}/duplicate", response_model=LabelOut, status_code=status.HTTP_201_CREATED
)
async def duplicate_label(label_id: int, session: SessionDep, user: UserDep):
    source = await get_label(session, label_id)
    label = Label(
        name=f"{source.name[:193]} (copy)",  # names are at most 200 characters
        description=source.description,
        kind=source.kind,
        zpl=source.zpl,
        design=source.design,
        width_mm=source.width_mm,
        height_mm=source.height_mm,
        dpi=source.dpi,
        variables=source.variables,
        tags=list(source.tags),
        created_by=user.identity,
    )
    session.add(label)
    await session.commit()
    await session.refresh(label)
    return label


@router.get("/labels/{label_id}/preview.png", response_class=Response, responses=PNG_RESPONSE)
async def preview_label(label_id: int, session: SessionDep):
    label = await get_label(session, label_id)
    return png_response(await run_in_threadpool(label_preview, label))


@router.get("/labels/{label_id}/export.zpl")
async def export_label(label_id: int, session: SessionDep):
    label = await get_label(session, label_id)
    filename = "".join(c if c.isalnum() or c in "-_ " else "_" for c in label.name) or "label"
    return Response(
        label.zpl,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": attachment(f"{filename}.zpl")},
    )


@router.get("/labels/{label_id}/variables", response_model=list[VariableDef])
async def read_variables(label_id: int, session: SessionDep):
    return label_definitions(await get_label(session, label_id))


@router.put("/labels/{label_id}/variables", response_model=list[VariableDef])
async def update_variables(label_id: int, body: VariableDefsIn, session: SessionDep):
    label = await get_label(session, label_id)
    apply_content(label, variables=body)
    await session.commit()
    return label_definitions(label)


def _example_value(definition: VariableDef) -> str:
    if definition.default:
        return definition.default
    if definition.type == "number":
        return "1"
    if definition.type == "date":
        return date.today().isoformat()
    return f"example {definition.name}"


@router.get("/labels/{label_id}/sample-data.{fmt}")
async def sample_data(
    label_id: int, fmt: Literal["csv", "json", "yaml", "xlsx"], session: SessionDep
):
    label = await get_label(session, label_id)
    definitions = label_definitions(label)
    columns = [d.name for d in definitions] + ["copies"]
    row = {d.name: _example_value(d) for d in definitions} | {"copies": "1"}
    filename = f"sample-{label.id}.{fmt}"
    headers = {"Content-Disposition": attachment(filename)}
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        writer.writerow(row)
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
    if fmt == "json":
        body = json.dumps([row], ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json", headers=headers)
    if fmt == "yaml":
        body = yaml.safe_dump([row], allow_unicode=True, sort_keys=False)
        return Response(body, media_type="application/yaml", headers=headers)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(columns)
    sheet.append([row[c] for c in columns])
    buf = io.BytesIO()
    workbook.save(buf)
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/templates/{label_id}/preview.png", response_class=Response, responses=PNG_RESPONSE)
async def preview_template(label_id: int, body: TemplatePreviewRequest, session: SessionDep):
    label = await get_label(session, label_id)
    return png_response(await run_in_threadpool(label_preview, label, body.variables))
