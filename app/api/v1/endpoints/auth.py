"""
AIB OCR Subsystem — Auth Endpoints

POST /auth/login   — получить JWT токен
GET  /auth/me      — информация о текущем пользователе
POST /auth/refresh — обновить токен (TODO: refresh tokens)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import (
    authenticate_user, create_access_token,
    require_auth, TokenData, Token,
)

router = APIRouter()


@router.post(
    "/login",
    response_model=Token,
    summary="Получить токен доступа",
    description="""
Аутентификация по логину и паролю.
Возвращает JWT Bearer токен для доступа к защищённым endpoints.

**Тестовые учётные записи (MVP):**
- `admin` / `changeme_admin` — полный доступ
- `operator` / `changeme_operator` — загрузка и просмотр документов
- `auditor` / `changeme_auditor` — только просмотр
    """,
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """
    Стандартный OAuth2 Password Flow.
    Принимает form-data: username + password.
    """
    user = authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={
        "sub": user.username,
        "role": user.role,
    })

    return token


@router.get(
    "/me",
    summary="Информация о текущем пользователе",
)
async def get_me(
    current_user: TokenData = Depends(require_auth),
):
    """Возвращает данные аутентифицированного пользователя"""
    return {
        "username": current_user.username,
        "role": current_user.role,
    }
