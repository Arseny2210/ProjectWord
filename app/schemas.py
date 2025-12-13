from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="Имя пользователя (3–50 символов)")
    password: str = Field(..., min_length=6, description="Пароль (минимум 6 символов, максимум 72 байта)")

    @validator('password')
    def validate_password_length_bytes(cls, v):
        password_bytes = v.encode('utf-8')
        if len(password_bytes) > 72:
            raise ValueError('Пароль не должен превышать 72 байта (ограничение bcrypt)')
        return v
class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True

class CardCreate(BaseModel):
    foreign_word: str
    native_translation: str
    example: Optional[str] = None

class CardUpdate(BaseModel):
    foreign_word: Optional[str] = None
    native_translation: Optional[str] = None
    example: Optional[str] = None
    is_completed: Optional[bool] = None

class CardOut(BaseModel):
    id: int
    foreign_word: str
    native_translation: str
    example: Optional[str]
    is_completed: bool
    owner_id: int

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class ProgressOut(BaseModel):
    total_cards: int
    completed_cards: int
    marked_important: int

    class Config:
        from_attributes = True
        
class ProgressBase(BaseModel):
    total_cards: Optional[int] = 0
    completed_cards: Optional[int] = 0
    marked_important: Optional[int] = 0

class ProgressCreate(ProgressBase):
    pass

class ProgressUpdate(ProgressBase):
    pass

class ProgressOut(ProgressBase):
    id: int
    user_id: int
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class UserCardProgressBase(BaseModel):
    is_completed: Optional[bool] = False
    completed_at: Optional[datetime] = None

class UserCardProgressCreate(UserCardProgressBase):
    user_id: int
    card_id: int

class UserCardProgressUpdate(UserCardProgressBase):
    pass

class UserCardProgressOut(UserCardProgressBase):
    id: int
    user_id: int
    card_id: int
    
    class Config:
        from_attributes = True

class CardOut(BaseModel):
    id: int
    foreign_word: str
    native_translation: str
    example: Optional[str]
    owner_id: int
    is_public: Optional[bool] = True

    class Config:
        from_attributes = True