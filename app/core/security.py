"""
AIB OCR Subsystem — Security / Authentication
JWT-аутентификация и управление пользователями

Схема:
  POST /api/v1/auth/login → {access_token, token_type}
  Все защищённые endpoints: Authorization: Bearer <token>
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import settings

# ── Password hashing ─────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── OAuth2 scheme ─────────────────────────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,          # False → не падаем если токена нет (опциональная аутентификация)
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int   # секунды


class UserInDB(BaseModel):
    username: str
    hashed_password: str
    role: str           # operator | auditor | admin
    is_active: bool = True


# ── In-memory users (MVP — замените на PostgreSQL в продакшне) ────────────────
USERS_DB: Dict[str, UserInDB] = {}


def _init_default_users():
    """Инициализирует встроенных пользователей (ИСПРАВЛЕНО ДЛЯ ЛОКАЛЬНОГО ЗАПУСКА)"""
    global USERS_DB
    
    # Мы жестко задаем короткие пароли, чтобы избежать ошибки "longer than 72 bytes" от bcrypt
    USERS_DB = {
        "admin": UserInDB(
            username="admin",
            hashed_password=pwd_context.hash("admin"), # Пароль: admin
            role="admin",
        ),
        "operator": UserInDB(
            username="operator",
            hashed_password=pwd_context.hash("operator"), # Пароль: operator
            role="operator",
        ),
        "auditor": UserInDB(
            username="auditor",
            hashed_password=pwd_context.hash("auditor"), # Пароль: auditor
            role="auditor",
        ),
    }


_init_default_users()


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(data: Dict[str, Any]) -> Token:
    """Создаёт JWT access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    to_encode["iat"] = datetime.now(timezone.utc)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return Token(
        access_token=encoded_jwt,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    """Проверяет логин/пароль, возвращает пользователя или None"""
    user = USERS_DB.get(username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def decode_token(token: str) -> TokenData:
    """Декодирует JWT токен, поднимает исключение при ошибке"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        username: str = payload.get("sub")
        role: str = payload.get("role", "operator")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недопустимые данные токена",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenData(username=username, role=role)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный или истёкший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[TokenData]:
    """
    Зависимость: опциональная аутентификация.
    Если токен не передан — возвращает None (для endpoint'ов без auth).
    """
    if not token:
        return None
    return decode_token(token)


async def require_auth(
    token: Optional[str] = Depends(oauth2_scheme),
) -> TokenData:
    """
    Зависимость: обязательная аутентификация.
    Поднимает 401 если токен отсутствует или невалиден.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(token)


async def require_admin(
    current_user: TokenData = Depends(require_auth),
) -> TokenData:
    """Зависимость: только для администраторов"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль: admin",
        )
    return current_user


async def require_operator_or_admin(
    current_user: TokenData = Depends(require_auth),
) -> TokenData:
    """Зависимость: оператор или администратор"""
    if current_user.role not in ("operator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль: operator или admin",
        )
    return current_user