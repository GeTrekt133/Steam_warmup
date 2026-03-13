"""
Fernet AES-256 обёртка для шифрования данных аккаунтов.

Fernet — симметричное шифрование (один ключ для шифрования и расшифровки).
Используется для защиты логинов/паролей Steam-аккаунтов в БД.
Ключ автоматически генерируется и сохраняется в .env при первом запуске.
"""

from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy init Fernet с ключом из настроек."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.FERNET_KEY.encode())
    return _fernet


def encrypt(data: str | None) -> str | None:
    """Шифрует строку → зашифрованная строка (base64). None → None."""
    if data is None:
        return None
    return _get_fernet().encrypt(data.encode()).decode()


def decrypt(encrypted_data: str | None) -> str | None:
    """Расшифровывает строку обратно. None → None."""
    if encrypted_data is None:
        return None
    return _get_fernet().decrypt(encrypted_data.encode()).decode()
