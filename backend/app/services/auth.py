"""
Auth сервис: JWT токены, хеширование паролей, HWID.

Как это работает:
- При регистрации пароль хешируется через bcrypt и сохраняется в БД.
- При логине пароль сверяется с хешем.
- JWT токен содержит user_id и hwid, действует 24 часа.
- HWID (Hardware ID) — уникальный идентификатор машины пользователя,
  используется для привязки лицензии к конкретному ПК.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Хеширует пароль через bcrypt. Результат нельзя расшифровать обратно."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Сверяет введённый пароль с хешем из БД."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(user_id: int, hwid: str | None = None) -> str:
    """
    Создаёт JWT токен.

    JWT (JSON Web Token) — это подписанная строка с данными пользователя.
    Клиент отправляет его в заголовке Authorization: Bearer <token>.
    Сервер проверяет подпись и извлекает данные без обращения к БД.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),  # subject — кто владелец токена
        "hwid": hwid,
        "exp": expire,  # expiration — когда токен станет невалидным
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    Декодирует JWT токен. Возвращает payload или None если токен невалиден.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None
