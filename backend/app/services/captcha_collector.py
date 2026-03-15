"""
Сервис сбора датасета капч (hCaptcha + FunCaptcha).

Сохраняет изображения и метаданные для обучения/тестирования солверов.
Изображения — PNG на диске, метаданные — JSONL (по строке на челлендж).

hCaptcha: API-based сбор (без браузера, кроме HSW-генератора).
FunCaptcha: Playwright-based скриншоты (рендерится в iframe).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from app.captcha.hcaptcha_solver import HSWGenerator, version, _simple_motion_data
from app.config import settings

logger = logging.getLogger(__name__)

STEAM_SITEKEY = "f5561ba9-8f1e-40ca-9b5b-a0b3f719ef34"
STEAM_HOST = "store.steampowered.com"


@dataclass
class CollectResult:
    collected: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


class CaptchaCollector:
    """Сбор датасета капч."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, dataset_dir: str | None = None):
        self.dataset_dir = Path(dataset_dir or settings.DATASET_DIR)
        self._hcaptcha_dir = self.dataset_dir / "hcaptcha"
        self._funcaptcha_dir = self.dataset_dir / "funcaptcha"
        self._ensure_dirs()

    def _ensure_dirs(self):
        """Создаём структуру папок."""
        (self._hcaptcha_dir / "images").mkdir(parents=True, exist_ok=True)
        (self._funcaptcha_dir / "images").mkdir(parents=True, exist_ok=True)

    # ── hCaptcha (API-based) ─────────────────────────────────

    async def collect_hcaptcha(
        self,
        count: int = 10,
        proxy: str | None = None,
    ) -> CollectResult:
        """
        Собрать count hCaptcha челленджей через API.

        Args:
            count: количество челленджей
            proxy: строка прокси "http://host:port"
        """
        result = CollectResult()

        for i in range(count):
            try:
                session_id = await asyncio.to_thread(
                    self._collect_one_hcaptcha, proxy
                )
                result.collected += 1
                logger.info("hCaptcha [%d/%d] собран: %s", i + 1, count, session_id)
            except Exception as e:
                result.errors += 1
                msg = f"hCaptcha [{i + 1}/{count}]: {e}"
                result.error_messages.append(msg)
                logger.warning(msg)
            # Задержка между запросами (анти-рейтлимит)
            if i < count - 1:
                await asyncio.sleep(2)

        return result

    def _collect_one_hcaptcha(self, proxy: str | None = None) -> str:
        """Собрать один hCaptcha челлендж. Возвращает session_id."""
        session_id = uuid.uuid4().hex[:12]
        session = self._create_session(proxy)
        ver = version()
        sitekey = STEAM_SITEKEY
        host = STEAM_HOST

        # 1. checksiteconfig
        sc = session.post(
            "https://hcaptcha.com/checksiteconfig",
            params={"v": ver, "sitekey": sitekey, "host": host, "sc": "1", "swa": "1", "spst": "1"},
        )
        siteconfig = sc.json()

        if "c" not in siteconfig:
            raise Exception(f"checksiteconfig failed: {json.dumps(siteconfig)[:200]}")

        # 2. HSW token
        hsw_gen = HSWGenerator()
        try:
            hsw1 = hsw_gen.generate(siteconfig["c"]["req"], host)
            if not hsw1:
                raise Exception("HSW generation failed")

            motion = _simple_motion_data(self.USER_AGENT, f"https://{host}")

            # 3. getcaptcha (первый запрос)
            data1 = {
                "v": ver, "sitekey": sitekey, "host": host, "hl": "en",
                "motionData": json.dumps(motion),
                "pdc": json.dumps({"s": round(time.time() * 1000), "n": 0, "p": 0, "gcs": 10}),
                "n": hsw1, "c": json.dumps(siteconfig["c"]), "pst": "false",
            }
            cap1 = session.post(f"https://hcaptcha.com/getcaptcha/{sitekey}", data=data1).json()

            if "c" not in cap1:
                raise Exception(f"getcaptcha 1 failed: {json.dumps(cap1)[:200]}")

            # 4. getcaptcha (второй запрос — основной челлендж)
            hsw2 = hsw_gen.generate(cap1["c"]["req"], host)
            data2 = {
                "v": ver, "sitekey": sitekey, "host": host, "hl": "en",
                "a11y_tfe": "true",
                "action": "challenge-refresh",
                "old_ekey": cap1.get("key", ""),
                "extraData": json.dumps(cap1),
                "motionData": json.dumps(motion),
                "pdc": json.dumps({"s": round(time.time() * 1000), "n": 0, "p": 0, "gcs": 10}),
                "n": hsw2, "c": json.dumps(cap1["c"]), "pst": "false",
            }
            cap2 = session.post(f"https://hcaptcha.com/getcaptcha/{sitekey}", data=data2).json()

        finally:
            hsw_gen.close()

        request_type = cap2.get("request_type", "unknown")
        question = cap2.get("requester_question", {}).get("en", "")
        tasklist = cap2.get("tasklist", [])

        if not tasklist:
            raise Exception(f"No tasklist, type={request_type}")

        # 5. Скачиваем изображения
        images_meta: dict = {"background": None, "entities": []}
        entity_ids: list[str] = []
        images_dir = self._hcaptcha_dir / "images"

        for task_idx, task in enumerate(tasklist):
            # Фоновое изображение
            bg_url = task.get("datapoint_uri")
            if bg_url:
                bg_filename = f"{session_id}_bg.png"
                bg_data = requests.get(bg_url, timeout=15).content
                (images_dir / bg_filename).write_bytes(bg_data)
                images_meta["background"] = bg_filename

            # Сущности (entities)
            for ent_idx, ent in enumerate(task.get("entities", [])):
                ent_url = ent.get("entity_uri")
                ent_id = ent.get("entity_id", f"ent_{ent_idx}")
                if ent_url:
                    ent_filename = f"{session_id}_entity_{ent_idx}.png"
                    ent_data = requests.get(ent_url, timeout=15).content
                    (images_dir / ent_filename).write_bytes(ent_data)
                    images_meta["entities"].append(ent_filename)
                    entity_ids.append(ent_id)

        # 6. Записываем метаданные
        metadata = {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "steam",
            "request_type": request_type,
            "question": question,
            "sitekey": sitekey,
            "images": images_meta,
            "entity_ids": entity_ids,
            "challenge_key": cap2.get("key", ""),
            "task_count": len(tasklist),
            "proxy_used": proxy,
        }

        jsonl_path = self._hcaptcha_dir / "metadata.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(metadata, ensure_ascii=False) + "\n")

        return session_id

    def _create_session(self, proxy: str | None = None) -> requests.Session:
        """Создать requests-сессию для hCaptcha API."""
        session = requests.Session()
        session.headers.update({
            "host": "hcaptcha.com",
            "connection": "keep-alive",
            "accept": "application/json",
            "user-agent": self.USER_AGENT,
            "origin": "https://newassets.hcaptcha.com",
            "referer": "https://newassets.hcaptcha.com/",
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US;q=0.9",
        })
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        return session

    # ── FunCaptcha (Playwright скриншоты) ─────────────────────

    async def collect_funcaptcha(
        self,
        count: int = 5,
        proxy: dict | None = None,
    ) -> CollectResult:
        """
        Собрать count FunCaptcha скриншотов через Playwright.

        Args:
            count: количество сессий
            proxy: {"server": "http://host:port"} для Playwright
        """
        result = CollectResult()

        for i in range(count):
            try:
                loop = asyncio.get_event_loop()
                with ProcessPoolExecutor(max_workers=1) as pool:
                    session_id = await loop.run_in_executor(
                        pool, _collect_one_funcaptcha_sync,
                        str(self._funcaptcha_dir), proxy,
                    )
                result.collected += 1
                logger.info("FunCaptcha [%d/%d] собран: %s", i + 1, count, session_id)
            except Exception as e:
                result.errors += 1
                msg = f"FunCaptcha [{i + 1}/{count}]: {e}"
                result.error_messages.append(msg)
                logger.warning(msg)
            if i < count - 1:
                await asyncio.sleep(3)

        return result

    # ── Статистика ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Статистика собранного датасета."""
        stats = {}
        for name, dir_path in [("hcaptcha", self._hcaptcha_dir), ("funcaptcha", self._funcaptcha_dir)]:
            images_dir = dir_path / "images"
            jsonl_path = dir_path / "metadata.jsonl"

            image_count = len(list(images_dir.glob("*.png"))) if images_dir.exists() else 0
            image_size_mb = sum(f.stat().st_size for f in images_dir.glob("*.png")) / (1024 * 1024) if images_dir.exists() else 0

            sample_count = 0
            type_counts: dict[str, int] = {}
            if jsonl_path.exists():
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            sample_count += 1
                            try:
                                entry = json.loads(line)
                                rt = entry.get("request_type", "unknown")
                                type_counts[rt] = type_counts.get(rt, 0) + 1
                            except json.JSONDecodeError:
                                pass

            stats[name] = {
                "samples": sample_count,
                "images": image_count,
                "size_mb": round(image_size_mb, 2),
                "types": type_counts,
            }

        return stats

    def get_samples(self, source: str = "hcaptcha", limit: int = 10) -> list[dict]:
        """Последние N записей из metadata.jsonl."""
        dir_path = self._hcaptcha_dir if source == "hcaptcha" else self._funcaptcha_dir
        jsonl_path = dir_path / "metadata.jsonl"

        if not jsonl_path.exists():
            return []

        lines = jsonl_path.read_text("utf-8").strip().splitlines()
        recent = lines[-limit:] if len(lines) > limit else lines
        results = []
        for line in reversed(recent):
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return results


# ── FunCaptcha sync (отдельный процесс) ──────────────────────

def _collect_one_funcaptcha_sync(
    funcaptcha_dir: str,
    proxy: dict | None = None,
) -> str:
    """Sync: открыть Outlook signup, дойти до FunCaptcha, сделать скриншоты."""
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from playwright.sync_api import sync_playwright
    from app.services.profile_generator import (
        generate_email_address, generate_email_password,
        generate_first_name, generate_last_name, generate_birth_date,
    )

    session_id = uuid.uuid4().hex[:12]
    images_dir = Path(funcaptcha_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    pw = None
    browser = None

    try:
        pw = sync_playwright().start()

        launch_opts: dict = {
            "headless": False,
        }
        if proxy:
            launch_opts["proxy"] = proxy

        browser = pw.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        # Переходим на страницу регистрации
        page.goto("https://signup.live.com/signup", wait_until="domcontentloaded", timeout=30000)

        # Вводим email
        email = generate_email_address()
        email_input = page.locator('input[type="email"], input[name="MemberName"]').first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.fill(email)
        page.locator('input[type="submit"], button[type="submit"]').first.click()
        time.sleep(2)

        # Вводим пароль
        pwd_input = page.locator('input[type="password"]').first
        if pwd_input.count() > 0 and pwd_input.is_visible():
            pwd_input.fill(generate_email_password())
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            time.sleep(2)

        # Вводим имя
        first_input = page.locator('input[name="FirstName"]').first
        if first_input.count() > 0 and first_input.is_visible():
            first_input.fill(generate_first_name())
            page.locator('input[name="LastName"]').first.fill(generate_last_name())
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            time.sleep(2)

        # Дата рождения
        month_sel = page.locator('select[name="BirthMonth"]').first
        if month_sel.count() > 0 and month_sel.is_visible():
            m, d, y = generate_birth_date()
            month_sel.select_option(value=str(m))
            page.locator('select[name="BirthDay"]').first.select_option(value=str(d))
            page.locator('select[name="BirthYear"]').first.select_option(value=str(y))
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            time.sleep(5)

        # Ищем iframe капчи и делаем скриншоты
        screenshots = []
        captcha_frame = page.locator(
            'iframe[data-e2e="enforcement-frame"], '
            'iframe[id*="enforcementFrame"], '
            'iframe[title*="arkose"], '
            'iframe[src*="funcaptcha"]'
        ).first

        if captcha_frame.count() > 0:
            # Скриншот всей страницы с капчей
            page_filename = f"{session_id}_page.png"
            page.screenshot(path=str(images_dir / page_filename))
            screenshots.append(page_filename)

            # Скриншот iframe
            try:
                frame_filename = f"{session_id}_frame_0.png"
                captcha_frame.screenshot(path=str(images_dir / frame_filename))
                screenshots.append(frame_filename)
            except Exception:
                pass

            # Пробуем зайти внутрь iframe и сделать скриншоты
            try:
                frame = captcha_frame.content_frame()
                if frame:
                    # Ищем изображение капчи внутри iframe
                    challenge_img = frame.locator('img[class*="challenge"], img[id*="challenge"], canvas').first
                    if challenge_img.count() > 0:
                        img_filename = f"{session_id}_challenge.png"
                        challenge_img.screenshot(path=str(images_dir / img_filename))
                        screenshots.append(img_filename)
            except Exception:
                pass
        else:
            # Нет капчи — делаем скриншот текущего состояния для отладки
            debug_filename = f"{session_id}_no_captcha.png"
            page.screenshot(path=str(images_dir / debug_filename))
            screenshots.append(debug_filename)

        # Записываем метаданные
        metadata = {
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "outlook",
            "request_type": "funcaptcha",
            "question": "",
            "images": {"screenshots": screenshots},
            "captcha_found": captcha_frame.count() > 0 if 'captcha_frame' in dir() else False,
            "page_url": page.url,
            "proxy_used": proxy.get("server") if proxy else None,
        }

        jsonl_path = Path(funcaptcha_dir) / "metadata.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(metadata, ensure_ascii=False) + "\n")

        return session_id

    except Exception as e:
        raise Exception(f"FunCaptcha collection failed: {e}") from e

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
