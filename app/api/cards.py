from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import Card, User
from app.database import get_db
from app.auth import require_admin_cookie

router = APIRouter()

@router.post("/create", include_in_schema=False, response_model=None)
async def create_card_web(
    request: Request,
    foreign_word: str = Form(...),
    native_translation: str = Form(...),
    example: str = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_cookie)
):
    db_card = Card(
        foreign_word=foreign_word.strip(),
        native_translation=native_translation.strip(),
        example=example.strip() if example else None,
        owner_id=current_user.id,
        is_public=True 
    )
    db.add(db_card)
    await db.commit()
    await db.refresh(db_card)
    return RedirectResponse("/admin/cards", status_code=303)

@router.post("/{card_id}/delete", include_in_schema=False, response_model=None)
async def delete_card_web(
    request: Request,
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_cookie)
):
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    await db.execute(delete(Card).where(Card.id == card_id))
    await db.commit()
    return RedirectResponse("/admin/cards", status_code=303)