from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import Card, User
from app.database import get_db
from app.auth import require_admin_cookie, get_user_from_cookie
from typing import Optional

router = APIRouter(
    tags=["📚 Карточки (админ)"],
    dependencies=[Depends(require_admin_cookie)]
)

@router.post("/create",
    include_in_schema=False,
    summary="Создать новую карточку",
    description="""
    Добавляет новую карточку для изучения в систему.
    
    **Требования:**
    - Только для администраторов
    - Обязательные поля: foreign_word, native_translation
    
    **Особенности:**
    - Карточка автоматически помечается как общедоступная
    - Владельцем становится текущий админ
    
    **Параметры формы:**
    - `foreign_word`: Слово на иностранном языке
    - `native_translation`: Перевод на русский
    - `example`: Пример использования (опционально)
    
    **Возможные ошибки:**
    - `403`: Нет прав администратора
    - `422`: Отсутствуют обязательные поля
    """,
    response_class=RedirectResponse
)
async def create_card_web(
    request: Request,
    foreign_word: str = Form(..., min_length=1, description="Слово на иностранном языке"),
    native_translation: str = Form(..., min_length=1, description="Перевод на русский"),
    example: Optional[str] = Form(None, description="Пример использования в предложении"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_cookie)
):
    # Валидация данных
    if not foreign_word.strip() or not native_translation.strip():
        raise HTTPException(status_code=422, detail="Поля 'foreign_word' и 'native_translation' обязательны")
    
    db_card = Card(
        foreign_word=foreign_word.strip(),
        native_translation=native_translation.strip(),
        example=example.strip() if example and example.strip() else None,
        owner_id=current_user.id,
        is_public=True 
    )
    db.add(db_card)
    await db.commit()
    await db.refresh(db_card)
    
    return RedirectResponse("/admin/cards", status_code=303)

@router.post("/{card_id}/delete",
    include_in_schema=False,
    summary="Удалить карточку",
    description="""
    Удаляет карточку из системы навсегда.
    
    **Требования:**
    - Только для администраторов
    - Карточка должна существовать
    
    **Параметры:**
    - `card_id`: ID карточки для удаления
    
    **Последствия:**
    - У всех пользователей сбрасывается прогресс по этой карточке
    - Карточка исчезает из списка для изучения
    
    **Возможные ошибки:**
    - `403`: Нет прав администратора
    - `404`: Карточка не найдена
    """,
    response_class=RedirectResponse,
    responses={
        303: {"description": "Перенаправление на страницу управления карточками"},
        404: {"description": "Карточка не найдена"}
    }
)
async def delete_card_web(
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_cookie)
):
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(
            status_code=404,
            detail="Карточка не найдена",
            headers={"X-Error-Type": "card_not_found"}
        )
    
    await db.execute(delete(Card).where(Card.id == card_id))
    await db.commit()
    
    return RedirectResponse("/admin/cards", status_code=303)