"""
Сервис прокси: CRUD, парсинг форматов, проверка (ping), round-robin привязка.
"""

import re
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proxy import Proxy
from app.models.account import Account
from app.schemas.proxy import ProxyCreate, ProxyUpdate, ProxyImportResult, ProxyCheckResult


# ── CRUD ────────────────────────────────────────────────

async def create_proxy(db: AsyncSession, data: ProxyCreate, owner_id: int) -> Proxy:
    proxy = Proxy(
        host=data.host,
        port=data.port,
        protocol=data.protocol,
        username=data.username,
        password=data.password,
        owner_id=owner_id,
    )
    db.add(proxy)
    await db.commit()
    await db.refresh(proxy)
    return proxy


async def get_proxy(db: AsyncSession, proxy_id: int, owner_id: int) -> Proxy | None:
    result = await db.execute(
        select(Proxy).where(Proxy.id == proxy_id, Proxy.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_proxies(
    db: AsyncSession,
    owner_id: int,
    skip: int = 0,
    limit: int = 100,
    alive_only: bool = False,
) -> list[Proxy]:
    query = select(Proxy).where(Proxy.owner_id == owner_id)
    if alive_only:
        query = query.where(Proxy.is_alive == True)
    query = query.order_by(Proxy.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_proxies(db: AsyncSession, owner_id: int) -> int:
    result = await db.execute(
        select(func.count(Proxy.id)).where(Proxy.owner_id == owner_id)
    )
    return result.scalar_one()


async def update_proxy(
    db: AsyncSession, proxy_id: int, owner_id: int, data: ProxyUpdate
) -> Proxy | None:
    proxy = await get_proxy(db, proxy_id, owner_id)
    if not proxy:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(proxy, field, value)
    await db.commit()
    await db.refresh(proxy)
    return proxy


async def delete_proxy(db: AsyncSession, proxy_id: int, owner_id: int) -> bool:
    proxy = await get_proxy(db, proxy_id, owner_id)
    if not proxy:
        return False
    await db.delete(proxy)
    await db.commit()
    return True


# ── Парсинг ─────────────────────────────────────────────

def parse_proxy_line(line: str) -> dict | None:
    """
    Парсит одну строку прокси. Поддерживаемые форматы:
    - host:port
    - host:port:user:pass
    - protocol://host:port
    - protocol://user:pass@host:port
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    protocol = "http"
    username = None
    password = None

    # protocol://...
    proto_match = re.match(r'^(https?|socks[45])://', line, re.IGNORECASE)
    if proto_match:
        protocol = proto_match.group(1).lower()
        line = line[proto_match.end():]

    # user:pass@host:port
    if "@" in line:
        auth_part, host_part = line.rsplit("@", 1)
        if ":" in auth_part:
            username, password = auth_part.split(":", 1)
        parts = host_part.split(":")
    else:
        parts = line.split(":")

    if len(parts) < 2:
        return None

    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return None

    if port < 1 or port > 65535:
        return None

    # host:port:user:pass формат
    if len(parts) == 4 and not username:
        username = parts[2]
        password = parts[3]

    return {
        "host": host,
        "port": port,
        "protocol": protocol,
        "username": username or None,
        "password": password or None,
    }


async def import_from_txt(
    db: AsyncSession, content: str, owner_id: int
) -> ProxyImportResult:
    """Импорт прокси из текста. Пропускает дубликаты (по host:port)."""
    existing = await db.execute(
        select(Proxy.host, Proxy.port).where(Proxy.owner_id == owner_id)
    )
    existing_set = {(row[0], row[1]) for row in existing.all()}

    imported = 0
    skipped = 0
    errors: list[str] = []

    for i, line in enumerate(content.strip().splitlines(), 1):
        parsed = parse_proxy_line(line)
        if parsed is None:
            if line.strip() and not line.strip().startswith("#"):
                errors.append(f"Строка {i}: невалидный формат '{line.strip()}'")
            continue

        if (parsed["host"], parsed["port"]) in existing_set:
            skipped += 1
            continue

        proxy = Proxy(owner_id=owner_id, **parsed)
        db.add(proxy)
        existing_set.add((parsed["host"], parsed["port"]))
        imported += 1

    if imported > 0:
        await db.commit()

    return ProxyImportResult(imported=imported, skipped=skipped, errors=errors)


# ── Проверка (ping) ────────────────────────────────────

async def check_proxy(proxy: Proxy) -> ProxyCheckResult:
    """Проверяет один прокси — делает запрос через него к httpbin."""
    proxy_url = f"{proxy.protocol}://"
    if proxy.username and proxy.password:
        proxy_url += f"{proxy.username}:{proxy.password}@"
    proxy_url += f"{proxy.host}:{proxy.port}"

    try:
        start = time.monotonic()
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10.0,
        ) as client:
            r = await client.get("https://httpbin.org/ip")
            r.raise_for_status()
        ping_ms = int((time.monotonic() - start) * 1000)
        return ProxyCheckResult(
            id=proxy.id, host=proxy.host, port=proxy.port,
            is_alive=True, ping_ms=ping_ms,
        )
    except Exception as e:
        return ProxyCheckResult(
            id=proxy.id, host=proxy.host, port=proxy.port,
            is_alive=False, ping_ms=None, error=str(e)[:200],
        )


async def check_proxies(
    db: AsyncSession, proxy_ids: list[int], owner_id: int
) -> list[ProxyCheckResult]:
    """Проверяет список прокси и обновляет статус в БД."""
    import asyncio

    results = []
    for pid in proxy_ids:
        proxy = await get_proxy(db, pid, owner_id)
        if not proxy:
            continue

        result = await check_proxy(proxy)
        proxy.is_alive = result.is_alive
        proxy.ping_ms = result.ping_ms
        proxy.last_checked_at = datetime.now(timezone.utc)
        results.append(result)

    await db.commit()
    return results


async def check_all_proxies(db: AsyncSession, owner_id: int) -> list[ProxyCheckResult]:
    """Проверяет все прокси пользователя."""
    all_proxies = await get_proxies(db, owner_id, limit=1000)
    ids = [p.id for p in all_proxies]
    return await check_proxies(db, ids, owner_id)


# ── Round-robin привязка ────────────────────────────────

async def assign_proxies_round_robin(
    db: AsyncSession, account_ids: list[int], owner_id: int
) -> int:
    """
    Привязывает прокси к аккаунтам по кругу (round-robin).
    Использует только живые прокси. Возвращает количество привязанных.
    """
    alive_proxies = await get_proxies(db, owner_id, limit=1000, alive_only=True)
    if not alive_proxies:
        # Если нет проверенных — берём все
        alive_proxies = await get_proxies(db, owner_id, limit=1000)
    if not alive_proxies:
        return 0

    assigned = 0
    for i, aid in enumerate(account_ids):
        result = await db.execute(
            select(Account).where(Account.id == aid, Account.owner_id == owner_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            continue
        account.proxy_id = alive_proxies[i % len(alive_proxies)].id
        assigned += 1

    await db.commit()
    return assigned
