"""
Fernet AES-256 обёртка для шифрования данных аккаунтов.

Fernet — симметричное шифрование (один ключ для шифрования и расшифровки).
Используется для защиты логинов/паролей Steam-аккаунтов в БД.
Ключ хранится в .env файле (FERNET_KEY). Без ключа данные невозможно прочитать.
"""

from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy init Fernet с ключом из настроек."""
    global _fernet
    if _fernet is None:
        key = settings.FERNET_KEY
        if not key:
            # Генерируем ключ — но его нужно сохранить в .env!
            key = Fernet.generate_key().decode()
            print(f"[WARNING] Сгенерирован новый FERNET_KEY. Сохрани в .env: FERNET_KEY={key}")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(data: str) -> str:
    """Шифрует строку → возвращает зашифрованную строку (base64)."""
    return _get_fernet().encrypt(data.encode()).decode()


def decrypt(encrypted_data: str) -> str:
    """Расшифровывает строку обратно."""
    return _get_fernet().decrypt(encrypted_data.encode()).decode()
