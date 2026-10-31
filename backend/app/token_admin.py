"""Operator commands for API tokens, for when the web UI cannot do the job - for example the
tokens of someone who has left, which only they could revoke there.

    python -m app.token_admin list
    python -m app.token_admin revoke ID [ID ...]
    python -m app.token_admin revoke-owner OWNER_SUB

In the container: `docker compose exec app python -m app.token_admin list`.
"""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import create_engine, create_sessionmaker
from app.models import ApiToken
from app.tokens import token_status

Sessionmaker = async_sessionmaker[AsyncSession]


def _when(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if value else "-"


async def list_tokens(sessionmaker: Sessionmaker) -> list[str]:
    async with sessionmaker() as session:
        tokens = (await session.scalars(select(ApiToken).order_by(ApiToken.id))).all()
    header = f"{'ID':>4}  {'STATUS':<8}  {'NAME':<24}  {'TOKEN':<13}  {'LAST USED':<16}  OWNER"
    return [header] + [
        f"{t.id:>4}  {token_status(t):<8}  {t.name[:24]:<24}  {t.prefix + '...':<13}  "
        f"{_when(t.last_used_at):<16}  {t.owner_identity} (sub: {t.owner_sub})"
        for t in tokens
    ]


async def revoke_tokens(
    sessionmaker: Sessionmaker, *, ids: Sequence[int] = (), owner_sub: str | None = None
) -> int:
    """Revoke the given tokens, or all of an owner's; returns how many were newly revoked."""
    stmt = update(ApiToken).where(ApiToken.revoked_at.is_(None))
    stmt = stmt.where(ApiToken.id.in_(ids)) if ids else stmt.where(ApiToken.owner_sub == owner_sub)
    async with sessionmaker() as session:
        result = await session.execute(stmt.values(revoked_at=datetime.now(UTC)))
        await session.commit()
        return result.rowcount


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.token_admin", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show all API tokens")
    revoke = commands.add_parser("revoke", help="revoke tokens by id")
    revoke.add_argument("ids", nargs="+", type=int)
    owner = commands.add_parser("revoke-owner", help="revoke all tokens of one owner")
    owner.add_argument("owner_sub", help="the owner's sub, as shown by `list`")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace, sessionmaker: Sessionmaker) -> list[str]:
    if args.command == "list":
        return await list_tokens(sessionmaker)
    if args.command == "revoke":
        count = await revoke_tokens(sessionmaker, ids=args.ids)
    else:
        count = await revoke_tokens(sessionmaker, owner_sub=args.owner_sub)
    return [f"Revoked {count} token(s)"]


async def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    engine = create_engine(get_settings().database_url)
    try:
        for line in await run(args, create_sessionmaker(engine)):
            print(line)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
