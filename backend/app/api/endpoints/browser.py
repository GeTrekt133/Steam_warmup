"""
Эндпоинт для открытия Steam в Playwright-браузере.

Принимает данные аккаунта напрямую (без привязки к БД),
т.к. аккаунты хранятся в localStorage фронтенда.

Авторизация не требуется — данные приходят от фронтенда,
а бэкенд работает только на localhost.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.steam_browser import open_steam_browser_raw

router = APIRouter()


class ProxyData(BaseModel):
    host: str
    port: int
    protocol: str = "http"
    username: str | None = None
    password: str | None = None


class OpenBrowserRequest(BaseModel):
    login: str
    password: str
    shared_secret: str | None = None
    proxy: ProxyData | None = None


@router.post("/open")
async def open_browser(data: OpenBrowserRequest):
    """
    Открыть Steam в Chromium-браузере с автологином.

    Принимает логин/пароль/shared_secret напрямую от фронтенда.
    Запускает Playwright в отдельном потоке — endpoint сразу возвращает статус.
    """
    proxy_config = None
    if data.proxy:
        proxy_config = data.proxy.model_dump()

    # Запускаем браузер в отдельном потоке (внутри open_steam_browser_raw)
    open_steam_browser_raw(
        login=data.login,
        password=data.password,
        shared_secret=data.shared_secret,
        proxy_config=proxy_config,
    )

    return {
        "status": "launched",
        "message": f"Браузер открывается для {data.login}",
    }
