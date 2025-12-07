from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import User
from app.schemas import UserOut
from app.database import get_db
from app.auth import require_admin
from typing import List

router = APIRouter() 

@router.get("/", response_model=List[UserOut], summary="Получить всех пользователей (админ)")
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    result = await db.execute(select(User))
    return result.scalars().all()

@router.delete("/{user_id}", status_code=204, summary="Удалить пользователя (админ)")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить самого себя")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return