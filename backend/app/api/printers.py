import asyncio
import time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.api.deps import SessionDep, SettingsDep
from app.models import Printer
from app.printer.addresses import AddressNotAllowed
from app.printer.client import PrinterClient, PrinterError
from app.printer.commands import (
    ACTIONS,
    PrinterSettings,
    curated_settings,
    device_info,
    settings_to_zpl,
)
from app.printer.sgd import SgdValue
from app.schemas import (
    ActionOut,
    ConnectionTest,
    ConnectionTestResult,
    LabelSettingsGroup,
    PrinterIn,
    PrinterOut,
    PrinterSettingsOut,
    PrinterStatusOut,
    RawSetting,
)
from app.services.print_service import printer_client
from app.zpl.printer_settings import DEFAULT_POLICY, SETTING_GROUPS, Source, resolve_policy

router = APIRouter(prefix="/printers", tags=["printers"])


async def _get(session: SessionDep, printer_id: int) -> Printer:
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printer not found")
    return printer


def _bad_gateway(exc: PrinterError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


async def _check_address(settings: SettingsDep, host: str, port: int) -> None:
    """Refuse addresses printer connections would never be allowed to use. A name that does not
    resolve (yet) is accepted: every connection checks the address again."""
    try:
        await asyncio.wait_for(
            settings.printer_address_policy.resolve(host, port), timeout=settings.printer_timeout
        )
    except AddressNotAllowed as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except UnicodeError as exc:
        # The name cannot be encoded for DNS (an empty label as in "a..b", or one over 63
        # characters): no connection could ever use it.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid printer host name: {host}"
        ) from exc
    except OSError:  # failed lookup or TimeoutError
        pass


async def _clear_default(session: SessionDep, keep_id: int | None = None) -> None:
    stmt = update(Printer).values(is_default=False)
    if keep_id is not None:
        stmt = stmt.where(Printer.id != keep_id)
    await session.execute(stmt)


@router.get("", response_model=list[PrinterOut])
async def list_printers(session: SessionDep):
    result = await session.scalars(
        select(Printer).order_by(Printer.is_default.desc(), Printer.name)
    )
    return result.all()


@router.post("", response_model=PrinterOut, status_code=status.HTTP_201_CREATED)
async def create_printer(body: PrinterIn, session: SessionDep, settings: SettingsDep):
    await _check_address(settings, body.host, body.port)
    has_printers = await session.scalar(select(Printer.id).limit(1)) is not None
    printer = Printer(**body.model_dump())
    printer.is_default = body.is_default or not has_printers
    if printer.is_default:
        await _clear_default(session)
    session.add(printer)
    await session.commit()
    await session.refresh(printer)
    return printer


@router.get("/actions", response_model=list[ActionOut])
async def list_actions():
    return [ActionOut(action=name, description=desc) for name, (_, desc) in ACTIONS.items()]


@router.get("/label-settings", response_model=list[LabelSettingsGroup])
async def label_settings_groups():
    """Groups of printer settings in labels whose source can be chosen per printer."""
    return [
        LabelSettingsGroup(
            group=group, title=title, commands=sorted(codes), default=DEFAULT_POLICY[group]
        )
        for group, (title, codes) in SETTING_GROUPS.items()
    ]


@router.post("/test", response_model=ConnectionTestResult)
async def test_connection(body: ConnectionTest, settings: SettingsDep):
    client = PrinterClient(
        body.host,
        body.port,
        timeout=settings.printer_timeout,
        policy=settings.printer_address_policy,
    )
    try:
        ident = await client.host_identification()
    except PrinterError as exc:
        return ConnectionTestResult(ok=False, error=str(exc))
    return ConnectionTestResult(ok=True, model=ident.model, firmware=ident.firmware, dpi=ident.dpi)


@router.get("/{printer_id}", response_model=PrinterOut)
async def get_printer(printer_id: int, session: SessionDep):
    return await _get(session, printer_id)


@router.put("/{printer_id}", response_model=PrinterOut)
async def update_printer(
    printer_id: int, body: PrinterIn, session: SessionDep, settings: SettingsDep
):
    printer = await _get(session, printer_id)
    await _check_address(settings, body.host, body.port)
    for key, value in body.model_dump().items():
        setattr(printer, key, value)
    if body.is_default:
        await _clear_default(session, keep_id=printer.id)
    await session.commit()
    await session.refresh(printer)
    return printer


@router.delete("/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_printer(printer_id: int, session: SessionDep):
    printer = await _get(session, printer_id)
    was_default = printer.is_default
    await session.delete(printer)
    await session.flush()
    if was_default:
        replacement = await session.scalar(select(Printer).order_by(Printer.id).limit(1))
        if replacement:
            replacement.is_default = True
    await session.commit()


@router.post("/{printer_id}/identify", response_model=PrinterOut)
async def identify_printer(printer_id: int, session: SessionDep, settings: SettingsDep):
    printer = await _get(session, printer_id)
    try:
        ident = await printer_client(printer, settings).host_identification()
    except PrinterError as exc:
        raise _bad_gateway(exc) from exc
    printer.model, printer.firmware, printer.dpi = ident.model, ident.firmware, ident.dpi
    await session.commit()
    await session.refresh(printer)
    return printer


@router.put("/{printer_id}/label-settings", response_model=PrinterOut)
async def update_label_settings(printer_id: int, body: dict[str, Source], session: SessionDep):
    """Choose per group whether settings in labels or the printer's own settings are used."""
    unknown = set(body) - set(SETTING_GROUPS)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown groups: {', '.join(sorted(unknown))}"
        )
    printer = await _get(session, printer_id)
    printer.label_settings = resolve_policy(printer.label_settings) | body
    await session.commit()
    await session.refresh(printer)
    return printer


@router.get("/{printer_id}/status", response_model=PrinterStatusOut)
async def printer_status(printer_id: int, session: SessionDep, settings: SettingsDep):
    printer = await _get(session, printer_id)
    try:
        result = await printer_client(printer, settings).host_status()
    except PrinterError as exc:
        return PrinterStatusOut(online=False, error=str(exc))
    return PrinterStatusOut(
        online=True, ready=result.ready, problems=result.problems, details=result.to_dict()
    )


# allcv takes several seconds; the settings form and the raw list share one read.
SETTINGS_CACHE_SECONDS = 30.0
_settings_cache: dict[int, tuple[float, dict[str, SgdValue]]] = {}
_settings_locks: dict[int, asyncio.Lock] = {}


def forget_settings(printer_id: int) -> None:
    _settings_cache.pop(printer_id, None)


async def _all_settings(
    printer: Printer, settings: SettingsDep, *, refresh: bool = False
) -> dict[str, SgdValue]:
    async with _settings_locks.setdefault(printer.id, asyncio.Lock()):
        cached = _settings_cache.get(printer.id)
        if cached and not refresh and time.monotonic() - cached[0] < SETTINGS_CACHE_SECONDS:
            return cached[1]
        try:
            values = await printer_client(printer, settings).all_settings()
        except PrinterError as exc:
            raise _bad_gateway(exc) from exc
        _settings_cache[printer.id] = (time.monotonic(), values)
        return values


@router.get("/{printer_id}/settings", response_model=PrinterSettingsOut)
async def read_settings(
    printer_id: int, session: SessionDep, settings: SettingsDep, refresh: bool = False
):
    printer = await _get(session, printer_id)
    values = await _all_settings(printer, settings, refresh=refresh)
    info = device_info(values)
    # Fall back to what ~HI reported and to the address the app connects to.
    info["firmware"] = info["firmware"] or printer.firmware
    info["model"] = printer.model
    info["ip_address"] = info["ip_address"] or printer.host
    return PrinterSettingsOut(settings=curated_settings(values), info=info)


@router.get("/{printer_id}/settings/raw", response_model=list[RawSetting])
async def read_raw_settings(
    printer_id: int, session: SessionDep, settings: SettingsDep, refresh: bool = False
):
    printer = await _get(session, printer_id)
    values = await _all_settings(printer, settings, refresh=refresh)
    return [
        RawSetting(key=key, value=value.value, choices=value.choices)
        for key, value in sorted(values.items())
    ]


@router.put("/{printer_id}/settings")
async def write_settings(
    printer_id: int, body: PrinterSettings, session: SessionDep, settings: SettingsDep
) -> dict[str, str]:
    printer = await _get(session, printer_id)
    if not body.model_dump(exclude_none=True):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No settings to change")
    commands = settings_to_zpl(body)
    forget_settings(printer.id)
    try:
        await printer_client(printer, settings).send(commands)
    except PrinterError as exc:
        raise _bad_gateway(exc) from exc
    return {"sent": commands}


@router.post("/{printer_id}/actions/{action}")
async def run_action(
    printer_id: int, action: str, session: SessionDep, settings: SettingsDep
) -> dict[str, str]:
    if action not in ACTIONS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown action {action}")
    printer = await _get(session, printer_id)
    command, description = ACTIONS[action]
    forget_settings(printer.id)
    try:
        await printer_client(printer, settings).send(command)
    except PrinterError as exc:
        raise _bad_gateway(exc) from exc
    return {"action": action, "description": description, "sent": command}
