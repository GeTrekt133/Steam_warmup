"""
Сервис аккаунтов: CRUD, парсинг TXT, шифрование полей.

Все чувствительные поля (password, shared_secret, identity_secret, mafile_json)
шифруются при записи и расшифровываются при чтении через Fernet AES-256.
"""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.schemas.account import AccountCreate, AccountUpdate, AccountImportResult
from app.services.encryption import encrypt, decrypt


async def create_account(db: AsyncSession, data: AccountCreate, owner_id: int) -> Account:
    """Создаёт один аккаунт с шифрованием пароля."""
    account = Account(
        login=data.login,
        password_encrypted=encrypt(data.password),
        steam_id=data.steam_id,
        proxy_id=data.proxy_id,
        group_id=data.group_id,
        note=data.note,
        owner_id=owner_id,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def get_account(db: AsyncSession, account_id: int, owner_id: int) -> Account | None:
    """Получает аккаунт по ID (только свои)."""
    result = await db.execute(
        select(Account).where(Account.id == account_id, Account.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_accounts(
    db: AsyncSession,
    owner_id: int,
    skip: int = 0,
    limit: int = 100,
    group_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[Account]:
    """Список аккаунтов с фильтрацией и пагинацией."""
    query = select(Account).where(Account.owner_id == owner_id)

    if group_id is not None:
        query = query.where(Account.group_id == group_id)
    if status is not None:
        query = query.where(Account.status == status)
    if search:
        query = query.where(Account.login.ilike(f"%{search}%"))

    query = query.order_by(Account.id.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_accounts(db: AsyncSession, owner_id: int) -> int:
    """Общее количество аккаунтов пользователя."""
    result = await db.execute(
        select(func.count(Account.id)).where(Account.owner_id == owner_id)
    )
    return result.scalar_one()


async def update_account(
    db: AsyncSession, account_id: int, owner_id: int, data: AccountUpdate
) -> Account | None:
    """Обновляет аккаунт (частично)."""
    account = await get_account(db, account_id, owner_id)
    if not account:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # Шифруем пароль если обновляется
    if "password" in update_data and update_data["password"] is not None:
        account.password_encrypted = encrypt(update_data.pop("password"))

    for field, value in update_data.items():
        setattr(account, field, value)

    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, account_id: int, owner_id: int) -> bool:
    """Удаляет аккаунт. Возвращает True если удалён."""
    account = await get_account(db, account_id, owner_id)
    if not account:
        return False
    await db.delete(account)
    await db.commit()
    return True


async def delete_accounts_bulk(db: AsyncSession, account_ids: list[int], owner_id: int) -> int:
    """Массовое удаление. Возвращает количество удалённых."""
    deleted = 0
    for aid in account_ids:
        if await delete_account(db, aid, owner_id):
            deleted += 1
    return deleted


def parse_txt_content(content: str, delimiter: str = ":") -> list[tuple[str, str]]:
    """
    Парсит текст формата login:password (по строкам).
    Возвращает список (login, password). Пропускает пустые строки и невалидные.
    """
    results = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(delimiter, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            results.append((parts[0].strip(), parts[1].strip()))
    return results


async def import_from_txt(
    db: AsyncSession,
    content: str,
    owner_id: int,
    group_id: int | None = None,
    delimiter: str = ":",
) -> AccountImportResult:
    """
    Импортирует аккаунты из текста login:password.
    Пропускает дубликаты (по login в рамках owner).
    """
    parsed = parse_txt_content(content, delimiter)

    # Получаем существующие логины для проверки дубликатов
    existing = await db.execute(
        select(Account.login).where(Account.owner_id == owner_id)
    )
    existing_logins = {row[0] for row in existing.all()}

    imported = 0
    skipped = 0
    errors: list[str] = []

    for login, password in parsed:
        if login in existing_logins:
            skipped += 1
            continue
        try:
            account = Account(
                login=login,
                password_encrypted=encrypt(password),
                group_id=group_id,
                owner_id=owner_id,
            )
            db.add(account)
            existing_logins.add(login)
            imported += 1
        except Exception as e:
            errors.append(f"{login}: {str(e)}")

    if imported > 0:
        await db.commit()

    return AccountImportResult(imported=imported, skipped=skipped, errors=errors)


def get_decrypted_password(account: Account) -> str | None:
    """Расшифровывает пароль аккаунта (для внутреннего использования)."""
    return decrypt(account.password_encrypted)


# ── maFile ──────────────────────────────────────────────

def parse_mafile(mafile_json: dict) -> dict:
    """
    Извлекает ключевые поля из maFile JSON.

    maFile — JSON от SteamDesktopAuthenticator (SDA), содержит:
    - account_name: логин Steam
    - steamid / Session.SteamID: SteamID64
    - shared_secret: для генерации 2FA кодов
    - identity_secret: для подтверждения трейдов
    - Весь JSON сохраняется целиком (зашифрованным) на случай если нужны другие поля.
    """
    account_name = (
        mafile_json.get("account_name")
        or mafile_json.get("AccountName")
        or ""
    )

    # SteamID может быть в корне или в Session
    steam_id = str(
        mafile_json.get("steamid")
        or mafile_json.get("SteamID")
        or (mafile_json.get("Session") or {}).get("SteamID")
        or ""
    )

    shared_secret = (
        mafile_json.get("shared_secret")
        or mafile_json.get("SharedSecret")
        or ""
    )

    identity_secret = (
        mafile_json.get("identity_secret")
        or mafile_json.get("IdentitySecret")
        or ""
    )

    return {
        "account_name": account_name,
        "steam_id": steam_id if steam_id else None,
        "shared_secret": shared_secret if shared_secret else None,
        "identity_secret": identity_secret if identity_secret else None,
    }


async def import_mafile(
    db: AsyncSession,
    mafile_json: dict,
    owner_id: int,
    password: str | None = None,
    group_id: int | None = None,
) -> tuple[Account | None, str | None]:
    """
    Импортирует один maFile.
    Если аккаунт с таким login уже есть — обновляет SteamGuard данные.
    Возвращает (account, error_message).
    """
    import json

    parsed = parse_mafile(mafile_json)

    if not parsed["account_name"]:
        return None, "maFile не содержит account_name"

    login = parsed["account_name"]
    mafile_str = json.dumps(mafile_json, ensure_ascii=False)

    # Ищем существующий аккаунт по логину
    result = await db.execute(
        select(Account).where(Account.login == login, Account.owner_id == owner_id)
    )
    account = result.scalar_one_or_none()

    if account:
        # Обновляем SteamGuard данные
        account.shared_secret_encrypted = encrypt(parsed["shared_secret"])
        account.identity_secret_encrypted = encrypt(parsed["identity_secret"])
        account.mafile_json_encrypted = encrypt(mafile_str)
        if parsed["steam_id"]:
            account.steam_id = parsed["steam_id"]
        if password:
            account.password_encrypted = encrypt(password)
    else:
        # Создаём новый аккаунт
        account = Account(
            login=login,
            password_encrypted=encrypt(password or ""),
            steam_id=parsed["steam_id"],
            shared_secret_encrypted=encrypt(parsed["shared_secret"]),
            identity_secret_encrypted=encrypt(parsed["identity_secret"]),
            mafile_json_encrypted=encrypt(mafile_str),
            group_id=group_id,
            owner_id=owner_id,
        )
        db.add(account)

    await db.commit()
    await db.refresh(account)
    return account, None


async def save_guard_mafile(
    db: AsyncSession,
    account: Account,
    mafile_data: dict,
    shared_secret: str,
    identity_secret: str,
) -> Account:
    """
    Сохраняет maFile после привязки Guard через SteamGuardLinker.
    Обновляет shared_secret, identity_secret и полный maFile JSON.
    """
    import json

    account.shared_secret_encrypted = encrypt(shared_secret)
    account.identity_secret_encrypted = encrypt(identity_secret)
    account.mafile_json_encrypted = encrypt(json.dumps(mafile_data, ensure_ascii=False))

    if mafile_data.get("SteamID") and not account.steam_id:
        account.steam_id = str(mafile_data["SteamID"])

    await db.commit()
    await db.refresh(account)
    return account


async def import_mafiles_batch(
    db: AsyncSession,
    files: list[dict],
    owner_id: int,
) -> AccountImportResult:
    """
    Массовый импорт maFiles.
    files: список dict с ключами mafile_json, password (опц.), group_id (опц.)
    """
    imported = 0
    skipped = 0
    errors: list[str] = []

    for item in files:
        account, error = await import_mafile(
            db,
            mafile_json=item["mafile_json"],
            owner_id=owner_id,
            password=item.get("password"),
            group_id=item.get("group_id"),
        )
        if error:
            errors.append(error)
        elif account:
            imported += 1

    return AccountImportResult(imported=imported, skipped=skipped, errors=errors)
