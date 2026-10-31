import json
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, current_user
from app.config import Settings
from app.db import get_session
from app.render.renderer import RenderResult
from app.zpl import generator


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


PNG_RESPONSE: dict = {200: {"content": {"image/png": {}}, "description": "PNG preview"}}


def png_response(result: RenderResult) -> Response:
    return Response(
        content=result.png,
        media_type="image/png",
        headers={
            "X-Render-Warnings": json.dumps(result.warnings),
            "X-Label-Count": str(result.label_count),
            "Cache-Control": "no-store",
        },
    )


def mm_to_dots(value: float | None, dpi: int) -> int | None:
    return generator.mm_to_dots(value, dpi) if value else None
