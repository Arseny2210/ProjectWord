from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.schemas import UserCreate, UserOut, Token
from app.models import User
from app.auth import get_password_hash, create_access_token 
from app.auth import pwd_context
from app.database import get_db
from datetime import timedelta
from typing import Optional

router = APIRouter()


templates = Jinja2Templates(directory="templates")

@router.post("/register", response_model=UserOut, summary="Регистрация пользователя")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    password_bytes = user.password.encode('utf-8')
    if len(password_bytes) > 72:
        user.password = password_bytes[:72].decode('utf-8', errors='ignore')
    
    result = await db.execute(select(User).where(User.username == user.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
    
    hashed = get_password_hash(user.password)  # Теперь безопасно
    db_user = User(username=user.username, hashed_password=hashed)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.post("/login", response_model=Token, summary="Вход в систему (API)")
async def login(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == user.username))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=401, detail="Неверные учетные данные")
    
    if not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверные учетные данные")
    
    access_token = create_access_token(
        data={"sub": str(db_user.id)},
        expires_delta=timedelta(minutes=30)
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/register-page", include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@router.post("/register-web", include_in_schema=False)
async def register_web(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            password = password_bytes[:72].decode('utf-8', errors='ignore')
        
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
        
        hashed = get_password_hash(password)  # Теперь безопасно
        db_user = User(username=username, hashed_password=hashed)
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return RedirectResponse("/", status_code=303)
    except HTTPException as e:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": e.detail
        })
        
@router.post("/login-web", include_in_schema=False)
async def login_web(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    user_in = UserCreate(username=username, password=password)
    try:
        token_data = await login(user_in, db)
    except HTTPException:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Неверное имя пользователя или пароль"
        })
    
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token_data["access_token"],
        httponly=True,
        max_age=1800,
    )
    return response