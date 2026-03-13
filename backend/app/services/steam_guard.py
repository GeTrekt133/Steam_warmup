"""
Генерация Steam Guard 2FA кодов из shared_secret.

Алгоритм TOTP совместимый со Steam — использует собственный алфавит
и 30-секундные интервалы, как в SteamDesktopAuthenticator.
"""

import base64
import hashlib
import hmac
import struct
import time

# Steam использует свой алфавит вместо стандартного base32
_STEAM_CHARS = "23456789BCDFGHJKMNPQRTVWXY"


def generate_steam_guard_code(shared_secret: str) -> str:
    """
    Генерирует 5-символьный Steam Guard код из shared_secret.

    shared_secret — base64-строка из maFile.
    Возвращает код вида "V2K9R".
    """
    # Текущий 30-секундный интервал
    timestamp = int(time.time())
    time_bytes = struct.pack(">Q", timestamp // 30)

    # HMAC-SHA1
    secret_bytes = base64.b64decode(shared_secret)
    hmac_hash = hmac.new(secret_bytes, time_bytes, hashlib.sha1).digest()

    # Dynamic truncation (RFC 4226)
    offset = hmac_hash[-1] & 0x0F
    code_int = struct.unpack(">I", hmac_hash[offset : offset + 4])[0] & 0x7FFFFFFF

    # Конвертация в 5-символьный код из Steam-алфавита
    code_chars = []
    for _ in range(5):
        code_chars.append(_STEAM_CHARS[code_int % len(_STEAM_CHARS)])
        code_int //= len(_STEAM_CHARS)

    return "".join(code_chars)


def get_code_with_ttl(shared_secret: str) -> tuple[str, int]:
    """
    Возвращает (code, seconds_remaining) — код и сколько секунд он ещё валиден.
    """
    code = generate_steam_guard_code(shared_secret)
    seconds_remaining = 30 - (int(time.time()) % 30)
    return code, seconds_remaining
