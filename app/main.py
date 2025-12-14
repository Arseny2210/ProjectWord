from typing import Any
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy import select, delete
from app.api import users, cards, progress, auth_routes
from app.database import Base, engine, get_db
from app.models import User, Card, Progress, UserCardProgress
from app.auth import get_user_from_cookie, require_admin_cookie
import sqlalchemy
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import datetime

app = FastAPI(
    title="Foreign Words Dictionary",
    description="Приложение для изучения английских слов",
    docs_url="/docs",
    redoc_url="/redoc"
)

templates = Jinja2Templates(directory="templates")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Обработчик для всех HTTP исключений
    """
    if exc.status_code == 404:
        try:
            async for db in get_db():
                current_user = await get_user_from_cookie(request, db)
                break
        except Exception:
            current_user = None
        
        return templates.TemplateResponse(
            "404.html",
            {
                "request": request,
                "current_user": current_user,
                "error_code": 404,
                "error_message": "Страница не найдена"
            },
            status_code=404
        )
    
    # Для JSON-запросов возвращаем JSON
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    
    # Для HTML-запросов показываем страницу ошибки
    if exc.status_code == 401:
        return templates.TemplateResponse(
            "401.html",
            {
                "request": request,
                "timestamp": datetime.now().strftime("%Y%m%d%H%M%S"),
            },
            status_code=401
        )
    elif exc.status_code == 403:
        return templates.TemplateResponse(
            "403.html",
            {
                "request": request,
                "error_message": "Доступ запрещен"
            },
            status_code=403
        )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    accept = request.headers.get("accept", "")

    wants_html = (
        "text/html" in accept.lower()
        or request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")
    )

    if wants_html:
        current_user = None
        try:
            async for db in get_db():
                current_user = await get_user_from_cookie(request, db)
                break
        except Exception:
            pass

        error_messages = []
        for error in exc.errors():
            loc = " -> ".join(str(x) for x in error.get("loc", []))
            msg = error.get("msg", "Ошибка валидации")
            error_messages.append(f"{loc}: {msg}")

        return templates.TemplateResponse(
            "422.html",
            {
                "request": request,
                "current_user": current_user,
                "error_message": "Проверьте введённые данные",
                "validation_errors": error_messages,
            },
            status_code=422,
        )

    # API / JSON
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.on_event("startup")
async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        result = await conn.execute(
            sqlalchemy.text("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        )
        admin_count = result.scalar()
        
        if admin_count == 0:
            result = await conn.execute(
                sqlalchemy.text("SELECT COUNT(*) FROM users")
            )
            user_count = result.scalar()
            
            if user_count > 0:
                await conn.execute(
                    sqlalchemy.text("UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users)")
                )
                print("Первый пользователь назначен администратором")
        
        await conn.commit()

app.include_router(auth_routes.router, prefix="/auth")
app.include_router(cards.router, prefix="/cards")
app.include_router(users.router, prefix="/admin/users")
app.include_router(progress.router, prefix="/progress")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_model=None, response_class=HTMLResponse,tags=["🌐 WEB"])
async def index(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dev/make-admin/{username}",tags=["🌐 WEB"])
async def dev_make_admin(username: str, db: Any = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user:
        user.is_admin = True
        await db.commit()
        return {"status": "ok", "message": f"{username} назначен администратором"}
    return {"status": "error", "message": "Пользователь не найден"}

@app.get("/register", response_model=None, response_class=HTMLResponse, tags=["🌐 WEB"])
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/dashboard", response_model=None, response_class=HTMLResponse, tags=["🌐 WEB"])
async def dashboard(
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(get_user_from_cookie)
):
    if not current_user:
        return RedirectResponse("/", status_code=303)

    if current_user.is_admin:
        cards_result = await db.execute(select(Card))
        all_cards = cards_result.scalars().all()
        
        public_cards = [card for card in all_cards if getattr(card, 'is_public', False)]
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "is_admin": current_user.is_admin
            },
            "is_admin": True,
            "admin_stats": {
                "total_cards": len(all_cards),
                "public_cards": len(public_cards)
            },
            "cards": [] 
        })
    else:
        try:
            result = await db.execute(select(Card))
            all_cards = result.scalars().all()
            
            user_cards = []
            for card in all_cards:
                is_public = getattr(card, 'is_public', False)
                if is_public:
                    owner_result = await db.execute(select(User).where(User.id == card.owner_id))
                    owner = owner_result.scalar_one_or_none()
                    if owner and owner.is_admin:
                        user_cards.append(card)
        except Exception as e:
            print(f"Ошибка при получении карточек: {e}")
            user_cards = []

        prog_result = await db.execute(
            select(Progress).where(Progress.user_id == current_user.id)
        )
        prog = prog_result.scalar_one_or_none()
        
        if not prog:
            prog = Progress(
                user_id=current_user.id,
                total_cards=len(user_cards),
                completed_cards=0,
                marked_important=0
            )
            db.add(prog)
            await db.commit()
            await db.refresh(prog)

        cards_data = []
        for c in user_cards:
            user_progress = None
            try:
                progress_result = await db.execute(
                    select(UserCardProgress).where(
                        UserCardProgress.user_id == current_user.id,
                        UserCardProgress.card_id == c.id
                    )
                )
                user_progress = progress_result.scalar_one_or_none()
            except Exception as e:
                print(f"Ошибка при получении прогресса по карточке {c.id}: {e}")
                user_progress = None
            
            is_completed = user_progress.is_completed if user_progress else False
            
            cards_data.append({
                "id": c.id,
                "foreign_word": c.foreign_word,
                "native_translation": c.native_translation,
                "example": c.example if c.example else "",
                "is_completed": is_completed 
            })

        user_learned_cards = 0
        for c in user_cards:
            try:
                progress_result = await db.execute(
                    select(UserCardProgress).where(
                        UserCardProgress.user_id == current_user.id,
                        UserCardProgress.card_id == c.id,
                        UserCardProgress.is_completed == True
                    )
                )
                user_progress = progress_result.scalar_one_or_none()
                if user_progress and user_progress.is_completed:
                    user_learned_cards += 1
            except Exception as e:
                print(f"Ошибка при проверке изучения карточки {c.id}: {e}")
                continue

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "is_admin": current_user.is_admin
            },
            "is_admin": False,
            "cards": cards_data,
            "progress": {
                "total_cards": len(user_cards),
                "completed_cards": user_learned_cards,
                "remaining_cards": len(user_cards) - user_learned_cards
            }
        })

@app.get("/admin/cards", response_model=None, response_class=HTMLResponse, tags=["🌐 WEB"])
async def admin_cards_page(
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(require_admin_cookie)
):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    
    result = await db.execute(select(Card))
    cards = result.scalars().all()
    
    users_result = await db.execute(select(User))
    users = {user.id: user.username for user in users_result.scalars().all()}
    
    progress_result = await db.execute(
        select(UserCardProgress).where(UserCardProgress.user_id == current_user.id)
    )
    progress_records = progress_result.scalars().all()
    
    progress_dict = {record.card_id: record.is_completed for record in progress_records}
    
    cards_data = []
    for card in cards:
        is_completed_by_user = progress_dict.get(card.id, False)
        
        owner_name = users.get(card.owner_id, f"ID: {card.owner_id}")
        cards_data.append({
            "id": card.id,
            "foreign_word": card.foreign_word,
            "native_translation": card.native_translation,
            "example": card.example if card.example else "",
            "is_completed": is_completed_by_user,  
            "is_public": getattr(card, 'is_public', False),
            "owner_id": card.owner_id,
            "owner_name": owner_name
        })
    
    return templates.TemplateResponse("admin/cards.html", {
        "request": request,
        "cards": cards_data
    })

@app.get("/admin/users", response_model=None, response_class=HTMLResponse, tags=["🌐 WEB"])
async def admin_users_page(
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(require_admin_cookie)
):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    all_users = result.scalars().all()
    
    users_data = []
    for user in all_users:
        prog_result = await db.execute(
            select(Progress).where(Progress.user_id == user.id)
        )
        progress = prog_result.scalar_one_or_none()
        
        users_data.append({
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "created_at": user.created_at.strftime("%d.%m.%Y %H:%M"),
            "cards_created": len(user.cards),
            "completed_cards": progress.completed_cards if progress else 0,
            "total_cards": progress.total_cards if progress else 0
        })
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "users": users_data,
        "current_user_id": current_user.id
    })

@app.post("/admin/users/{user_id}/toggle-active",tags=["🌐 WEB"])
async def toggle_user_active(
    user_id: int,
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(require_admin_cookie)
):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    
    if user_id == current_user.id:
        return RedirectResponse("/admin/users", status_code=303)
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.is_active = not user.is_active
    await db.commit()
    
    return RedirectResponse("/admin/users", status_code=303)

@app.post("/admin/users/{user_id}/delete", tags=["🌐 WEB"])
async def delete_user_admin(
    user_id: int,
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(require_admin_cookie)
):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    
    if user_id == current_user.id:
        return RedirectResponse("/admin/users", status_code=303)
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    try:
        await db.execute(delete(Progress).where(Progress.user_id == user_id))
        await db.execute(delete(UserCardProgress).where(UserCardProgress.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        
        await db.commit()
        
        return RedirectResponse("/admin/users", status_code=303)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")

@app.post("/admin/users/{user_id}/toggle-admin",tags=["🌐 WEB"])
async def toggle_user_admin(
    user_id: int,
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(require_admin_cookie)
):
    if not current_user or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    
    if user_id == current_user.id:
        return RedirectResponse("/admin/users", status_code=303)
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.is_admin = not user.is_admin
    await db.commit()
    
    return RedirectResponse("/admin/users", status_code=303)

@app.post("/learn/{card_id}", tags=["🌐 WEB"])
async def learn_card(
    card_id: int,
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(get_user_from_cookie)
):
    if not current_user or current_user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    is_public = getattr(card, 'is_public', False)
    if not is_public:
        raise HTTPException(status_code=403, detail="Карточка недоступна для изучения")
    
    progress_result = await db.execute(
        select(UserCardProgress).where(
            UserCardProgress.user_id == current_user.id,
            UserCardProgress.card_id == card_id
        )
    )
    user_card_progress = progress_result.scalar_one_or_none()
    
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
    
    prog_result = await db.execute(
        select(Progress).where(Progress.user_id == current_user.id)
    )
    prog = prog_result.scalar_one_or_none()
    
    if prog:
        prog.completed_cards += 1
        await db.commit()
    else:
        prog = Progress(
            user_id=current_user.id,
            total_cards=1,
            completed_cards=1,
            marked_important=0
        )
        db.add(prog)
        await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)

@app.post("/unlearn/{card_id}", tags=["🌐 WEB"])
async def unlearn_card(
    card_id: int,
    request: Request,
    db: Any = Depends(get_db),
    current_user: Any = Depends(get_user_from_cookie)
):
    if not current_user or current_user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    
    result = await db.execute(select(Card).where(Card.id == card_id))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    
    is_public = getattr(card, 'is_public', False)
    if not is_public:
        raise HTTPException(status_code=403, detail="Карточка недоступна для изучения")
    
    progress_result = await db.execute(
        select(UserCardProgress).where(
            UserCardProgress.user_id == current_user.id,
            UserCardProgress.card_id == card_id
        )
    )
    user_card_progress = progress_result.scalar_one_or_none()
    
    if user_card_progress:
        user_card_progress.is_completed = False
        user_card_progress.completed_at = None
        await db.commit()
    
    prog_result = await db.execute(
        select(Progress).where(Progress.user_id == current_user.id)
    )
    prog = prog_result.scalar_one_or_none()
    
    if not prog:
        raise HTTPException(status_code=404, detail="Прогресс не найден")
    
    if prog.completed_cards > 0:
        prog.completed_cards -= 1
        await db.commit()
    
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/logout", response_model=None, tags=["🌐 WEB"])
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("access_token")
    return response