from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models import Progress, Card, User, UserCardProgress
from app.schemas import ProgressCreate, ProgressUpdate, ProgressOut
from app.database import get_db
from app.auth import get_current_active_user, require_admin, get_user_from_cookie
from typing import List, Optional
from jose import JWTError, jwt

router = APIRouter(
    tags=["📈 Прогресс обучения"]
)

async def get_user_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Получение пользователя из cookie с полной валидацией"""
    token = request.cookies.get("access_token")
    if not token or not token.startswith("Bearer "):
        return None
    
    token = token.split(" ")[1]
    SECRET_KEY = "your-secret-key-change-in-prod"
    ALGORITHM = "HS256"
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()
        return user if user and user.is_active else None
    
    except (JWTError, ValueError, TypeError):
        return None

@router.post("/",
    response_model=ProgressOut,
    summary="Создать запись прогресса",
    description="""
    Инициализирует запись прогресса для нового пользователя.
    
    **Автоматические значения:**
    - `total_cards`: Количество доступных карточек
    - `completed_cards`: 0 (по умолчанию)
    - `marked_important`: 0 (по умолчанию)
    
    **Требования:**
    - Авторизованный пользователь
    
    **Возможные ошибки:**
    - `401`: Неавторизованный доступ
    - `409`: Запись прогресса уже существует
    """,
    status_code=201,
    responses={
        201: {"description": "Запись прогресса успешно создана"},
        409: {"description": "Запись прогресса уже существует для этого пользователя"}
    }
)
async def create_progress(
    progress: ProgressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    # Проверка существования прогресса
    existing = await db.execute(select(Progress).where(Progress.user_id == current_user.id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Запись прогресса уже существует для этого пользователя",
            headers={"X-Error-Type": "progress_exists"}
        )
    
    # Получение количества общедоступных карточек
    cards_result = await db.execute(select(Card).where(Card.is_public == True))
    total_cards = len(cards_result.scalars().all())
    
    db_progress = Progress(
        user_id=current_user.id,
        total_cards=total_cards,
        completed_cards=progress.completed_cards,
        marked_important=progress.marked_important
    )
    db.add(db_progress)
    await db.commit()
    await db.refresh(db_progress)
    return db_progress

@router.get("/",
    response_model=List[ProgressOut],
    summary="Получить прогресс всех пользователей (админ)",
    description="""
    Возвращает полную статистику прогресса всех пользователей.
    
    **Данные в ответе:**
    - `total_cards`: Общее количество карточек
    - `completed_cards`: Изученные карточки
    - `marked_important`: Важные карточки
    - `user_id`: ID пользователя
    
    **Требования:**
    - Только для администраторов
    
    **Пагинация:**
    - `skip`: Количество пропускаемых записей
    - `limit`: Максимальное количество записей (макс. 100)
    """,
    dependencies=[Depends(require_admin)],
    responses={
        200: {"description": "Успешное получение данных прогресса"},
        403: {"description": "Нет прав администратора"}
    }
)
async def read_progress_all(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    if limit > 100:
        limit = 100
    
    result = await db.execute(
        select(Progress)
        .offset(skip)
        .limit(limit)
        .order_by(Progress.completed_cards.desc())
    )
    return result.scalars().all()

@router.get("/my",
    response_model=ProgressOut,
    summary="Получить свой прогресс",
    description="""
    Возвращает персональную статистику прогресса обучения.
    
    **Данные в ответе:**
    - Общее количество карточек
    - Количество изученных карточек
    - Количество отмеченных как важные
    - Процент завершения
    
    **Требования:**
    - Авторизованный пользователь
    - Инициализированный прогресс
    
    **Возможные ошибки:**
    - `401`: Неавторизованный доступ
    - `404`: Прогресс не инициализирован
    """,
    responses={
        200: {"description": "Успешное получение персонального прогресса"},
        404: {"description": "Прогресс не найден. Сначала изучите хотя бы одну карточку."}
    }
)
async def read_my_progress(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(Progress).where(Progress.user_id == current_user.id)
    )
    progress = result.scalar_one_or_none()
    if not progress:
        raise HTTPException(
            status_code=404,
            detail="Ваш прогресс не инициализирован. Перейдите на дашборд для автоматической инициализации.",
            headers={"X-Error-Type": "progress_not_initialized"}
        )
    return progress

@router.put("/",
    response_model=ProgressOut,
    summary="Обновить свой прогресс",
    description="""
    Обновляет персональные данные прогресса.
    
    **Обновляемые поля:**
    - `completed_cards`: Количество изученных карточек
    - `marked_important`: Количество важных карточек
    
    **Ограничения:**
    - Нельзя установить completed_cards > total_cards
    - Нельзя установить отрицательные значения
    
    **Требования:**
    - Авторизованный пользователь
    - Существующая запись прогресса
    
    **Возможные ошибки:**
    - `400`: Некорректные значения полей
    - `404`: Прогресс не найден
    """,
    responses={
        200: {"description": "Прогресс успешно обновлен"},
        400: {"description": "Некорректные значения для обновления"},
        404: {"description": "Прогресс не найден"}
    }
)
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
        raise HTTPException(
            status_code=404,
            detail="Прогресс не найден",
            headers={"X-Error-Type": "progress_not_found"}
        )
    
    # Валидация значений
    if progress_update.completed_cards is not None:
        if progress_update.completed_cards < 0:
            raise HTTPException(status_code=400, detail="completed_cards не может быть отрицательным")
        if progress_update.completed_cards > db_progress.total_cards:
            raise HTTPException(
                status_code=400,
                detail=f"completed_cards не может превышать total_cards ({db_progress.total_cards})"
            )
    
    if progress_update.marked_important is not None and progress_update.marked_important < 0:
        raise HTTPException(status_code=400, detail="marked_important не может быть отрицательным")
    
    # Обновление только переданных полей
    update_data = progress_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_progress, key, value)
    
    await db.commit()
    await db.refresh(db_progress)
    return db_progress

@router.post("/complete/{card_id}/web",
    include_in_schema=False,
    summary="Отметить карточку как изученную",
    description="""
    Обновляет статус карточки на "изучено" для текущего пользователя.
    
    **Логика работы:**
    1. Проверяет существование карточки
    2. Проверяет доступность карточки (только общедоступные)
    3. Обновляет или создает запись в UserCardProgress
    4. Увеличивает счетчик completed_cards в общем прогрессе
    
    **Особенности:**
    - Работает только для обычных пользователей (не для админов)
    - Автоматически инициализирует прогресс при первом изучении
    
    **Параметры:**
    - `card_id`: ID карточки для изучения
    
    **Возможные ошибки:**
    - `401`: Требуется авторизация
    - `403`: Карточка недоступна для изучения
    - `404`: Карточка не найдена
    """,
    response_class=RedirectResponse
)
async def complete_card_web(
    card_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_user_from_cookie)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация для изучения карточек")
    
    if current_user.is_admin:
        raise HTTPException(status_code=403, detail="Администраторы не могут изучать карточки")
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    if not card.is_public:
        raise HTTPException(status_code=403, detail="Карточка недоступна для изучения")
    
    # Проверка/создание записи прогресса
    prog_result = await db.execute(select(Progress).where(Progress.user_id == current_user.id))
    prog = prog_result.scalar_one_or_none()
    
    if not prog:
        # Инициализация прогресса
        cards_result = await db.execute(select(Card).where(Card.is_public == True))
        total_cards = len(cards_result.scalars().all())
        
        prog = Progress(
            user_id=current_user.id,
            total_cards=total_cards,
            completed_cards=0,
            marked_important=0
        )
        db.add(prog)
    
    # Обновление прогресса по карточке
    progress_result = await db.execute(
        select(UserCardProgress).where(
            UserCardProgress.user_id == current_user.id,
            UserCardProgress.card_id == card_id
        )
    )
    user_card_progress = progress_result.scalar_one_or_none()
    
    if user_card_progress:
        if not user_card_progress.is_completed:  # Только если еще не изучена
            user_card_progress.is_completed = True
            user_card_progress.completed_at = datetime.utcnow()
            prog.completed_cards += 1
    else:
        user_card_progress = UserCardProgress(
            user_id=current_user.id,
            card_id=card_id,
            is_completed=True,
            completed_at=datetime.utcnow()
        )
        db.add(user_card_progress)
        prog.completed_cards += 1
    
    await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)

@router.post("/reset/{card_id}/web",
    include_in_schema=False,
    summary="Сбросить прогресс по карточке",
    description="""
    Отмечает карточку как "не изученную" для текущего пользователя.
    
    **Логика работы:**
    1. Проверяет права доступа к карточке
    2. Обновляет статус изучения
    3. Уменьшает счетчик completed_cards в общем прогрессе
    
    **Важно:**
    - Работает только для своих карточек или общедоступных от админов
    - Администраторы могут сбрасывать прогресс любых карточек
    
    **Параметры:**
    - `card_id`: ID карточки для сброса
    
    **Возможные ошибки:**
    - `401`: Требуется авторизация
    - `403`: Нет доступа к карточке
    - `404`: Карточка не найдена или прогресс отсутствует
    """,
    response_class=RedirectResponse
)
async def reset_card_web(
    card_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_user_from_cookie)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    # Проверка доступа к карточке
    if not current_user.is_admin:
        if card.owner_id != current_user.id:
            owner_result = await db.execute(select(User).where(User.id == card.owner_id))
            owner = owner_result.scalar_one_or_none()
            if not owner or not owner.is_admin or not card.is_public:
                raise HTTPException(status_code=403, detail="Нет доступа к этой карточке")
    
    # Получение прогресса по карточке
    progress_result = await db.execute(
        select(UserCardProgress).where(
            UserCardProgress.user_id == current_user.id,
            UserCardProgress.card_id == card_id
        )
    )
    user_card_progress = progress_result.scalar_one_or_none()
    
    if not user_card_progress or not user_card_progress.is_completed:
        raise HTTPException(status_code=404, detail="Карточка не была изучена или прогресс отсутствует")
    
    # Сброс прогресса
    user_card_progress.is_completed = False
    user_card_progress.completed_at = None
    
    # Обновление общего прогресса
    prog_result = await db.execute(select(Progress).where(Progress.user_id == current_user.id))
    prog = prog_result.scalar_one_or_none()
    
    if prog and prog.completed_cards > 0:
        prog.completed_cards -= 1
    
    await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)