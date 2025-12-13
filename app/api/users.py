from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models import User
from app.schemas import UserOut
from app.database import get_db
from app.auth import require_admin
from typing import List

router = APIRouter(
    tags=["👥 Пользователи (админ)"],
    dependencies=[Depends(require_admin)]
)

@router.get("/",
    response_model=List[UserOut],
    summary="Получить список всех пользователей",
    description="""
    Возвращает полный список пользователей системы с их данными.
    
    **Данные в ответе:**
    - `id`: Уникальный идентификатор
    - `username`: Имя пользователя
    - `is_admin`: Флаг администратора
    - `is_active`: Статус активности
    - `created_at`: Дата регистрации
    
    **Требования:**
    - Только для администраторов
    
    **Сортировка:**
    - По убыванию даты создания (новые пользователи первыми)
    """,
    response_description="Список пользователей системы"
)
async def get_all_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()

@router.delete("/{user_id}",
    status_code=204,
    summary="Удалить пользователя",
    description="""
    Полностью удаляет пользователя из системы.
    
    **Важные ограничения:**
    - Нельзя удалить самого себя
    - Удаляются все связанные данные:
        - Прогресс изучения
        - Личные карточки
    
    **Параметры:**
    - `user_id`: ID пользователя для удаления
    
    **Возможные ошибки:**
    - `400`: Попытка удалить свой аккаунт
    - `403`: Отсутствие прав администратора
    - `404`: Пользователь не найден
    """,
    responses={
        204: {"description": "Пользователь успешно удален"},
        400: {"description": "Нельзя удалить самого себя"},
        404: {"description": "Пользователь не найден"}
    }
)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить свой аккаунт. Сначала передайте права администратора другому пользователю.",
            headers={"X-Error-Type": "self_deletion"}
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден",
            headers={"X-Error-Type": "user_not_found"}
        )
    
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return