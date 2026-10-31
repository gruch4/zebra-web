"""Background execution of mass-print batches."""

import asyncio
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.models import Label, PrintBatch, Printer, PrintJob
from app.printer.client import PrinterError
from app.services.print_service import apply_copies, printer_client, render_label
from app.zpl.printer_settings import strip_printer_settings

log = logging.getLogger(__name__)


def _prepare_chunk(
    label: Label, chunk: list[dict], policy: dict[str, str] | None
) -> tuple[list[str], str]:
    """The ZPL of each row (as recorded) and the data sent for the chunk, with copies."""
    rendered = [
        strip_printer_settings(render_label(label, row["values"]), policy).zpl for row in chunk
    ]
    payload = "".join(
        apply_copies(zpl, row.get("copies", 1)) for zpl, row in zip(rendered, chunk, strict=True)
    )
    return rendered, payload


class BatchRunner:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessionmaker = sessionmaker
        self.settings = settings
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self.cancelled: set[int] = set()

    def start(self, batch_id: int) -> asyncio.Task[None]:
        task = asyncio.create_task(self._run(batch_id), name=f"batch-{batch_id}")
        self.tasks[batch_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(batch_id, None))
        return task

    def is_running(self, batch_id: int) -> bool:
        return batch_id in self.tasks

    def cancel(self, batch_id: int) -> None:
        self.cancelled.add(batch_id)

    async def wait(self, batch_id: int) -> None:
        task = self.tasks.get(batch_id)
        if task:
            await task

    async def shutdown(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def recover(self) -> None:
        """Mark batches left running by a previous process as failed."""
        async with self.sessionmaker() as session:
            await session.execute(
                update(PrintBatch)
                .where(PrintBatch.status.in_(["queued", "running"]))
                .values(
                    status="failed",
                    error="Interrupted by an application restart",
                    finished_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def _run(self, batch_id: int) -> None:
        try:
            async with self.sessionmaker() as session:
                await self._execute(session, batch_id)
        except Exception:
            log.exception("Batch %s crashed", batch_id)
            async with self.sessionmaker() as session:
                batch = await session.get(PrintBatch, batch_id)
                if batch:
                    batch.status = "failed"
                    batch.error = "Internal error while printing"
                    batch.finished_at = datetime.now(UTC)
                    await session.commit()
        finally:
            self.cancelled.discard(batch_id)

    async def _execute(self, session: AsyncSession, batch_id: int) -> None:
        batch = await session.get(PrintBatch, batch_id)
        if batch is None:
            return
        printer = await session.get(Printer, batch.printer_id) if batch.printer_id else None
        label = await session.get(Label, batch.label_id) if batch.label_id else None
        if printer is None or label is None:
            batch.status = "failed"
            batch.error = "The printer or label no longer exists"
            batch.finished_at = datetime.now(UTC)
            await session.commit()
            return

        batch.status = "running"
        await session.commit()
        client = printer_client(printer, self.settings)
        chunk_size = max(1, self.settings.batch_chunk_size)
        rows = list(batch.rows)
        final_status = "done"

        for start in range(0, len(rows), chunk_size):
            if batch_id in self.cancelled:
                final_status = "cancelled"
                break
            try:
                printer_status = await client.host_status()
            except PrinterError as exc:
                log.warning("Batch %s: status check failed: %s", batch_id, exc)
            else:
                if printer_status.blocking_problems:
                    batch.error = "Printer not ready: " + ", ".join(
                        printer_status.blocking_problems
                    )
                    final_status = "failed"
                    break

            chunk = rows[start : start + chunk_size]
            rendered, payload = await run_in_threadpool(
                _prepare_chunk, label, chunk, printer.label_settings
            )
            started = time.monotonic()
            error = None
            try:
                await client.send(payload)
            except PrinterError as exc:
                error = str(exc)
            duration = round((time.monotonic() - started) * 1000)
            for zpl, row in zip(rendered, chunk, strict=True):
                session.add(
                    PrintJob(
                        printer_id=printer.id,
                        printer_name=printer.name,
                        printer_host=f"{printer.host}:{printer.port}",
                        dpi=printer.dpi,
                        label_id=label.id,
                        label_name=label.name,
                        source="batch",
                        zpl=zpl,
                        variables=row["values"],
                        copies=row.get("copies", 1),
                        status="failed" if error else "sent",
                        error=error,
                        duration_ms=duration,
                        batch_id=batch.id,
                        batch_row=row["row"],
                        created_by=batch.created_by,
                    )
                )
            if error:
                batch.failed += len(chunk)
                batch.error = error
                final_status = "failed"
            else:
                batch.sent += len(chunk)
            await session.commit()
            if error:
                break

        batch.status = final_status
        batch.finished_at = datetime.now(UTC)
        await session.commit()
