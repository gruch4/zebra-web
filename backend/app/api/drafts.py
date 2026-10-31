import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from sqlalchemy import delete

from app.api.deps import SessionDep, UserDep
from app.models import UserDraft
from app.schemas import DraftIn, DraftOut

router = APIRouter(prefix="/drafts", tags=["drafts"])

MAX_DRAFT_BYTES = 6 * 1024 * 1024
DraftName = Annotated[str, Path(pattern=r"^[a-z0-9_-]{1,50}$")]


@router.get("/{name}", response_model=DraftOut)
async def read_draft(name: DraftName, session: SessionDep, user: UserDep):
    """The current user's saved work in progress (empty when nothing is saved)."""
    draft = await session.get(UserDraft, (user.sub, name))
    if draft is None:
        return DraftOut(name=name, data={}, updated_at=None)
    return DraftOut(name=name, data=draft.data, updated_at=draft.updated_at)


@router.put("/{name}", response_model=DraftOut)
async def save_draft(name: DraftName, body: DraftIn, session: SessionDep, user: UserDep):
    if len(json.dumps(body.data)) > MAX_DRAFT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The draft is too large")
    draft = await session.get(UserDraft, (user.sub, name))
    if draft is None:
        draft = UserDraft(user_sub=user.sub, name=name, data=body.data)
        session.add(draft)
    else:
        draft.data = body.data
    await session.commit()
    await session.refresh(draft)
    return DraftOut(name=name, data=draft.data, updated_at=draft.updated_at)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(name: DraftName, session: SessionDep, user: UserDep):
    await session.execute(
        delete(UserDraft).where(UserDraft.user_sub == user.sub, UserDraft.name == name)
    )
    await session.commit()
