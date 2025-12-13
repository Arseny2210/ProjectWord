from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.schemas import UserCreate, UserOut, Token
from app.models import User
from app.auth import get_password_hash, create_access_token, pwd_context
from app.database import get_db
from datetime import timedelta
from pydantic import ValidationError
from typing import Optional

router = APIRouter(
    tags=["🔐 Аутентификация"]
)
templates = Jinja2Templates(directory="templates")

async def get_user_from_form(
    username: str = Form(..., description="Имя пользователя (3-50 символов)"),
    password: str = Form(..., description="Пароль (минимум 6 символов)")
) -> UserCreate:
    """Преобразует данные формы в Pydantic-модель с валидацией"""
    try:
        return UserCreate(username=username, password=password)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

@router.post("/register",
    response_model=UserOut,
    summary="Регистрация нового пользователя",
    description="""
    Создает новый аккаунт в системе с валидацией данных.
    
    **Требования к данным:**
    - `username`: 3-50 символов, только буквы и цифры
    - `password`: минимум 6 символов, максимум 72 байта
    
    **Возможные ошибки:**
    - `400`: Имя пользователя уже занято
    - `422`: Некорректные данные (слишком короткий пароль, длинное имя)
    
    **Пример успешного ответа:**
    ```json
    {
        "id": 1,
        "username": "new_user",
        "is_admin": false,
        "created_at": "2023-09-15T12:30:45.123456"
    }
    ```
    """,
    response_description="Данные созданного пользователя",
    status_code=201
)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == user.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Имя пользователя уже занято",
            headers={"X-Error-Type": "username_taken"}
        )
    
    hashed = get_password_hash(user.password)
    db_user = User(username=user.username, hashed_password=hashed)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.post("/login",
    response_model=Token,
    summary="Вход в систему (API)",
    description="""
    Аутентифицирует пользователя и возвращает JWT-токен для доступа к защищенным ресурсам.
    
    **Требования:**
    - Корректные имя пользователя и пароль
    - Активный аккаунт
    
    **Пример запроса (через форму):**
    ```json
    {
        "grant_type": "password",
        "username": "user123",
        "password": "securepass123",
        "scope": "",
        "client_id": "",
        "client_secret": ""
    }
    ```
    
    **Возможные ошибки:**
    - `401`: Неверные учетные данные или неактивный пользователь
    - `422`: Некорректный формат запроса
    
    **Заголовки безопасности:**
    - `WWW-Authenticate: Bearer` при ошибке 401
    """,
    response_description="JWT-токен для авторизации",
    responses={
        401: {
            "description": "Неверные учетные данные",
            "headers": {"WWW-Authenticate": {"schema": {"type": "string"}, "description": "Тип аутентификации"}}
        }
    }
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == form_data.username))
    db_user = result.scalar_one_or_none()
    
    if not db_user or not pwd_context.verify(form_data.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверные учетные данные",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not db_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь заблокирован. Обратитесь к администратору.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(
        data={"sub": str(db_user.id)},
        expires_delta=timedelta(minutes=30)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/register-page", 
    include_in_schema=False,
    summary="Страница регистрации (HTML)",
    description="Отображает HTML-форму регистрации для веб-интерфейса"
)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post(
    "/register-web",
    include_in_schema=False,
    summary="Регистрация через веб-форму",
    description="""
    Обрабатывает регистрацию пользователя через HTML-форму.

    **Перенаправления:**
    - При успехе: на страницу входа
    - При ошибке: обратно на форму с сообщением

    **Валидация:**
    - Проверка длины имени и пароля
    - Уникальность имени пользователя
    """,
)
async def register_web(
    request: Request,
    username: str = Form(None),
    password: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    errors: list[str] = []
    if not username:
        errors.append("Имя пользователя обязательно")
    if not password:
        errors.append("Пароль обязателен")

    if errors:
        return templates.TemplateResponse(
            "422.html",
            {
                "request": request,
                "validation_errors": errors,
                "username": username,
            },
            status_code=422,
        )
    try:
        user_create = UserCreate(username=username, password=password)
    except ValidationError as e:
        return templates.TemplateResponse(
            "422.html",
            {
                "request": request,
                "validation_errors": [err["msg"] for err in e.errors()],
                "username": username,
            },
            status_code=422,
        )
    result = await db.execute(
        select(User).where(User.username == user_create.username)
    )
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Имя пользователя уже занято",
                "username": username,
            },
            status_code=400,
        )
    hashed_password = get_password_hash(user_create.password)
    db_user = User(
        username=user_create.username,
        hashed_password=hashed_password,
    )
    db.add(db_user)
    await db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key="registration_success",
        value="true",
        max_age=5,
        httponly=True,
        samesite="lax",
    )
    return response

@router.post("/login-web", include_in_schema=False)
async def login_web(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Неверное имя пользователя или пароль",
                "username": username
            },
            status_code=401
        )

    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Пользователь заблокирован",
                "username": username
            },
            status_code=401
        )

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=30)
    )

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=1800,
        samesite="lax"
    )
    return response


@router.get("/logout",
    include_in_schema=False,
    summary="Выход из системы",
    description="Удаляет аутентификационную куку и завершает сессию"
)
async def logout(response: Response):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("registration_success", path="/")
    return response