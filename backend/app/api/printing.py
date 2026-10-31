import base64

from fastapi import APIRouter, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    PNG_RESPONSE,
    SessionDep,
    SettingsDep,
    UserDep,
    mm_to_dots,
    png_response,
)
from app.models import Label
from app.render.renderer import RenderError, RenderResult, render_cache
from app.schemas import (
    EmbeddedSettingOut,
    PrinterSettingsInZpl,
    PrinterSettingsRequest,
    PrintJobOut,
    PrintRequest,
    RenderInfo,
    RenderRequest,
    VariablesOut,
    VariablesRequest,
)
from app.services.print_service import (
    check_resolution,
    get_printer,
    printer_policy,
    resolve_design,
    resolve_label,
    resolve_zpl,
    send_job,
    template_http_error,
)
from app.zpl.printer_settings import strip_printer_settings
from app.zpl.templating import TemplateError, extract_variables, substitute_zpl

router = APIRouter(tags=["print"])


@router.post("/print", response_model=PrintJobOut)
async def print_label(
    body: PrintRequest, session: SessionDep, settings: SettingsDep, user: UserDep
):
    printer = await get_printer(session, body.printer_id)
    label = None
    # Filling in a template tokenizes the whole ZPL, so it runs off the event loop.
    try:
        if body.label_id is not None:
            label = await session.get(Label, body.label_id)
            if label is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Label not found")
            zpl, values = await run_in_threadpool(resolve_label, label, body.variables)
            source = body.source or "archive"
        elif body.design is not None:
            zpl, values = await run_in_threadpool(
                resolve_design, body.design, body.variables, body.definitions
            )
            source = body.source or "designer"
        else:
            zpl, values = await run_in_threadpool(
                resolve_zpl, body.zpl or "", body.variables, body.definitions
            )
            source = body.source or "raw"
    except TemplateError as exc:
        raise template_http_error(exc) from exc
    check_resolution(printer, label, body.design)
    return await send_job(
        session,
        settings,
        printer,
        zpl,
        copies=body.copies,
        source=source,
        user=user,
        label=label,
        values=values,
        keep_printer_settings=body.keep_printer_settings,
    )


async def _render(body: RenderRequest, session: SessionDep) -> RenderResult:
    zpl = body.zpl
    if body.variables is not None:
        try:
            zpl = await run_in_threadpool(substitute_zpl, body.zpl, body.variables)
        except TemplateError as exc:
            raise template_http_error(exc) from exc
    if body.strip_printer_settings:
        policy = await printer_policy(session, body.printer_id)
        zpl = (await run_in_threadpool(strip_printer_settings, zpl, policy)).zpl
    try:
        return await run_in_threadpool(
            render_cache.render,
            zpl,
            dpi=body.dpi,
            width=mm_to_dots(body.width_mm, body.dpi),
            height=mm_to_dots(body.height_mm, body.dpi),
            index=body.index,
        )
    except RenderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/render", response_class=Response, responses=PNG_RESPONSE)
async def render_png(body: RenderRequest, session: SessionDep):
    return png_response(await _render(body, session))


@router.post("/render/info", response_model=RenderInfo)
async def render_info(body: RenderRequest, session: SessionDep):
    result = await _render(body, session)
    return RenderInfo(
        image="data:image/png;base64," + base64.b64encode(result.png).decode(),
        width=result.width,
        height=result.height,
        label_count=result.label_count,
        warnings=result.warnings,
    )


@router.post("/variables", response_model=VariablesOut)
async def detect_variables(body: VariablesRequest):
    return VariablesOut(variables=extract_variables(body.zpl))


@router.post("/zpl/printer-settings", response_model=PrinterSettingsInZpl)
async def printer_settings_in_zpl(body: PrinterSettingsRequest, session: SessionDep):
    """List printer settings embedded in ZPL: which are used and which the printer replaces."""
    policy = await printer_policy(session, body.printer_id)
    result = await run_in_threadpool(strip_printer_settings, body.zpl, policy)

    def out(items):
        return [
            EmbeddedSettingOut(command=i.command, description=i.description, group=i.group)
            for i in items
        ]

    return PrinterSettingsInZpl(zpl=result.zpl, removed=out(result.removed), kept=out(result.kept))
