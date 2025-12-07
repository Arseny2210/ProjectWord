from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models import Progress, Card, User, UserCardProgress
from app.schemas import ProgressCreate, ProgressUpdate, ProgressOut
from app.database import get_db
from app.auth import get_current_active_user, require_admin
from typing import List
from jose import JWTError, jwt

router = APIRouter()

async def get_user_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Получение пользователя из cookie"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    
    try:
        SECRET_KEY = "your-secret-key-change-in-prod"
        ALGORITHM = "HS256"
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()
        if user and not user.is_active:
            return None
        return user
    except JWTError:
        return None

@router.post("/", response_model=ProgressOut, summary="Создать запись прогресса")
async def create_progress(
    progress: ProgressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    db_progress = Progress(**progress.dict(), user_id=current_user.id)
    db.add(db_progress)
    await db.commit()
    await db.refresh(db_progress)
    return db_progress

@router.get("/", response_model=List[ProgressOut], summary="Получить весь прогресс (админ)")
async def read_progress_all(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    result = await db.execute(select(Progress).offset(skip).limit(limit))
    return result.scalars().all()

@router.get("/my", response_model=ProgressOut, summary="Получить свой прогресс")
async def read_my_progress(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(Progress).where(Progress.user_id == current_user.id)
    )
    progress = result.scalar_one_or_none()
    if not progress:
        raise HTTPException(status_code=404, detail="Прогресс не найден")
    return progress

@router.put("/", response_model=ProgressOut, summary="Обновить свой прогресс")
async def update_my_progress(
    progress_update: ProgressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(Progress).where(Progress.user_id == current_user.id)
    )
    db_progress = result.scalar_one_or_none()
    if not db_progress:
        raise HTTPException(status_code=404, detail="Прогресс не найден")
    await db.execute(
        update(Progress)
        .where(Progress.user_id == current_user.id)
        .values(**progress_update.dict(exclude_unset=True))
    )
    await db.commit()
    await db.refresh(db_progress)
    return db_progress

@router.post("/complete/{card_id}/web", include_in_schema=False, response_model=None)
async def complete_card_web(
    request: Request,
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_user_from_cookie)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    result = await db.execute(
        select(UserCardProgress).where(
            UserCardProgress.user_id == current_user.id,
            UserCardProgress.card_id == card_id
        )
    )
    user_card_progress = result.scalar_one_or_none()
    
    if user_card_progress:
        user_card_progress.is_completed = True
        user_card_progress.completed_at = datetime.utcnow()
    else:
        user_card_progress = UserCardProgress(
            user_id=current_user.id,
            card_id=card_id,
            is_completed=True,
            completed_at=datetime.utcnow()
        )
        db.add(user_card_progress)
    
    await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)

@router.post("/reset/{card_id}/web", include_in_schema=False, response_model=None)
async def reset_card_web(
    request: Request,
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_user_from_cookie)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Необходима авторизация")
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    if card.owner_id != current_user.id:
        owner_result = await db.execute(select(User).where(User.id == card.owner_id))
        owner = owner_result.scalar_one_or_none()
        is_public = getattr(card, 'is_public', False)
        
        if not owner or not owner.is_admin or not is_public:
            raise HTTPException(status_code=403, detail="Нет доступа к этой карточке")
    
    if card.is_completed:
        card.is_completed = False
        await db.commit()
        
        prog_result = await db.execute(
            select(Progress).where(Progress.user_id == current_user.id)
        )
        prog = prog_result.scalar_one_or_none()
        
        if prog and prog.completed_cards > 0:
            prog.completed_cards -= 1
            await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)