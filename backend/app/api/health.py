from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep, UserDep
from app.schemas import UserOut


async def health(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


async def me(user: UserDep, settings: SettingsDep) -> UserOut:
    return UserOut(
        sub=user.sub, email=user.email, name=user.name, auth_enabled=settings.auth_enabled
    )
