"""
Оркестратор полного цикла регистрации:
1. [CV + Chrome]     Регистрация почты Proton
2. [Playwright]      Регистрация Steam
3. [CV + Chrome]     Код подтверждения Steam из почты
4. [Playwright/HTTP] Подтверждение email Steam
5. [Playwright]      Привязка Steam Guard (SDA)
6. [CV + Chrome]     Код активации SDA из почты
7. [Playwright]      Финализация привязки Guard
"""
import sys
import time
import random
import logging
import argparse
from pathlib import Path
from dataclasses import dataclass

# Добавляем backend в path для импорта
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from chrome_launcher import ChromeLauncher, ChromeInstance
from screen_automation import ScreenAutomation
from human_behavior import HumanBehavior
from ocr_engine import OCREngine
from proton_cv import ProtonCV, gen_username, gen_password
from steam_cv import SteamPlaywright

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Результат полного цикла регистрации."""
    ok: bool
    email: str = ""
    email_password: str = ""
    steam_login: str = ""
    steam_password: str = ""
    mafile_path: str = ""
    revocation_code: str = ""
    error: str = ""


class FullRegistrationPipeline:
    """
    Полный цикл: Proton Mail → Steam → Steam Guard.
    Два окна: Chrome (CV) для почты, Playwright для Steam.
    """

    def __init__(self, proxy: str | None = None):
        self.proxy = proxy
        self.chrome_launcher = ChromeLauncher()

    def run_batch(self, count: int = 1) -> list[RegistrationResult]:
        """Зарегистрировать несколько аккаунтов."""
        results = []
        for i in range(count):
            logger.info(f"\n{'='*60}")
            logger.info(f"  Аккаунт {i + 1}/{count}")
            logger.info(f"{'='*60}")

            result = self.register_one()
            results.append(result)

            if result.ok:
                logger.info(f"  ✓ {result.email} | Steam: {result.steam_login}")
            else:
                logger.info(f"  ✗ {result.error}")

            # Пауза между аккаунтами (2-5 мин)
            if i < count - 1:
                wait = random.uniform(120, 300)
                logger.info(f"  Пауза {wait:.0f}с...")
                time.sleep(wait)

        ok_count = sum(1 for r in results if r.ok)
        logger.info(f"\n══ Готово: {ok_count}/{count} ══")
        return results

    def register_one(self) -> RegistrationResult:
        """Полный цикл регистрации одного аккаунта."""
        username = gen_username()
        password = gen_password()
        email = f"{username}@proton.me"
        chrome_inst = None

        try:
            # ═══════════════════════════════════════════════════════════
            # Шаг 1: Регистрация Proton Mail [CV + Chrome]
            # ═══════════════════════════════════════════════════════════
            logger.info("[Pipeline] Шаг 1: Регистрация Proton Mail...")

            chrome_inst = self.chrome_launcher.launch(
                proxy=self.proxy,
                window_size=(1280, 900),
                window_position=(0, 0),
            )
            time.sleep(3)  # ждём запуска Chrome

            human = HumanBehavior()
            screen = ScreenAutomation(chrome_inst, self.chrome_launcher, human)
            proton = ProtonCV(screen, human)

            proton_result = proton.register(username, password)
            if not proton_result["ok"]:
                return RegistrationResult(
                    ok=False, email=email, email_password=password,
                    error=f"Proton: {proton_result.get('msg', 'unknown')}"
                )

            logger.info(f"[Pipeline] Proton OK: {email}")

            # ═══════════════════════════════════════════════════════════
            # Шаг 2: Регистрация Steam [Playwright / HTTP API]
            # ═══════════════════════════════════════════════════════════
            logger.info("[Pipeline] Шаг 2: Регистрация Steam...")

            steam_login, steam_password = self._register_steam(email, password)
            if not steam_login:
                return RegistrationResult(
                    ok=False, email=email, email_password=password,
                    error="Steam registration failed"
                )

            logger.info(f"[Pipeline] Steam OK: {steam_login}")

            # ═══════════════════════════════════════════════════════════
            # Шаг 3: Код подтверждения Steam [CV + Chrome]
            # ═══════════════════════════════════════════════════════════
            logger.info("[Pipeline] Шаг 3: Чтение кода Steam из почты...")

            # Steam присылает ссылку подтверждения или код
            confirmation = proton.read_confirmation_link(
                subject_keywords=["Steam", "verify", "confirm", "email verification"],
                link_pattern=r"https?://store\.steampowered\.com/\S*",
                timeout=120,
            )

            if not confirmation:
                # Попробуем найти код вместо ссылки
                confirmation = proton.read_email_code(
                    subject_keywords=["Steam", "verify", "confirm"],
                    code_pattern=r"\b[A-Z0-9]{5}\b",
                    timeout=60,
                )

            if not confirmation:
                return RegistrationResult(
                    ok=False, email=email, email_password=password,
                    steam_login=steam_login, steam_password=steam_password,
                    error="Steam confirmation code/link not found"
                )

            # ═══════════════════════════════════════════════════════════
            # Шаг 4: Подтверждение Steam [HTTP]
            # ═══════════════════════════════════════════════════════════
            logger.info(f"[Pipeline] Шаг 4: Подтверждение Steam ({confirmation[:50]}...)")

            confirmed = self._confirm_steam_email(confirmation)
            if not confirmed:
                return RegistrationResult(
                    ok=False, email=email, email_password=password,
                    steam_login=steam_login, steam_password=steam_password,
                    error="Steam email confirmation failed"
                )

            # ═══════════════════════════════════════════════════════════
            # Шаг 5: Привязка Steam Guard [Playwright]
            # ═══════════════════════════════════════════════════════════
            logger.info("[Pipeline] Шаг 5: Привязка Steam Guard...")

            # Запускаем линковку, она запросит email код
            guard_result = self._link_steam_guard(
                steam_login, steam_password, email, password, proton
            )

            if not guard_result:
                return RegistrationResult(
                    ok=False, email=email, email_password=password,
                    steam_login=steam_login, steam_password=steam_password,
                    error="Steam Guard linking failed"
                )

            mafile_path, revocation_code = guard_result

            # ═══════════════════════════════════════════════════════════
            # Успех!
            # ═══════════════════════════════════════════════════════════
            return RegistrationResult(
                ok=True,
                email=email,
                email_password=password,
                steam_login=steam_login,
                steam_password=steam_password,
                mafile_path=mafile_path,
                revocation_code=revocation_code,
            )

        except Exception as e:
            logger.error(f"[Pipeline] Ошибка: {e}", exc_info=True)
            return RegistrationResult(
                ok=False, email=email, email_password=password,
                error=str(e)
            )
        finally:
            # Не закрываем Chrome — оставляем для проверки результата
            logger.info(f"[Pipeline] Chrome остаётся открытым (PID={chrome_inst.pid if chrome_inst else 'N/A'})")
            pass

    # ── Steam интеграция (заглушки — будут заменены реальными вызовами) ──

    def _register_steam(self, email: str, email_password: str) -> tuple[str, str]:
        """
        Регистрация Steam аккаунта.
        TODO: Подключить backend/app/services/steam_registration.py
        """
        try:
            # Импорт из backend
            from app.services.steam_registration import SteamRegistrationService
            service = SteamRegistrationService()

            # Генерация логина/пароля Steam
            steam_login = gen_username()
            steam_password = gen_password()

            # Вызов регистрации (HTTP API, не браузер)
            result = service.register(
                email=email,
                login=steam_login,
                password=steam_password,
                proxy=self.proxy,
            )

            if result.get("ok"):
                return steam_login, steam_password
            else:
                logger.error(f"Steam reg failed: {result.get('msg')}")
                return "", ""

        except ImportError:
            logger.warning("[Pipeline] SteamRegistrationService не найден, пропускаю")
            # Заглушка для тестирования пайплайна без backend
            return "", ""

    def _confirm_steam_email(self, confirmation: str) -> bool:
        """
        Подтверждение email Steam (клик по ссылке или ввод кода).
        TODO: Подключить backend
        """
        try:
            import requests
            if confirmation.startswith("http"):
                resp = requests.get(confirmation, timeout=30)
                return resp.status_code == 200
            else:
                logger.warning(f"Неизвестный формат подтверждения: {confirmation}")
                return False
        except Exception as e:
            logger.error(f"Steam confirm error: {e}")
            return False

    def _link_steam_guard(
        self,
        steam_login: str,
        steam_password: str,
        email: str,
        email_password: str,
        proton: ProtonCV,
    ) -> tuple[str, str] | None:
        """
        Привязка Steam Guard.
        Шаги 5-7: запуск линкера + чтение кодов из почты через CV.

        TODO: Подключить backend/app/services/steam_guard_linker.py
        """
        try:
            from app.services.steam_guard_linker import SteamGuardLinker
            linker = SteamGuardLinker()

            # Линкер должен уметь использовать callback для чтения email кодов
            # Вместо Playwright Outlook — используем ProtonCV

            def email_code_callback(subject_keywords, code_pattern, timeout):
                """Callback: читаем код через CV Chrome."""
                return proton.read_email_code(
                    subject_keywords=subject_keywords,
                    code_pattern=code_pattern,
                    timeout=timeout,
                )

            result = linker.link(
                login=steam_login,
                password=steam_password,
                email_code_provider=email_code_callback,
                proxy=self.proxy,
            )

            if result and result.get("ok"):
                return result.get("mafile_path", ""), result.get("revocation_code", "")

        except ImportError:
            logger.warning("[Pipeline] SteamGuardLinker не найден, пропускаю")

        return None


# ── Точка входа ───────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    ap = argparse.ArgumentParser(description="CV Pipeline: Proton + Steam + Guard")
    ap.add_argument("--proxy", default=None, help="Прокси (user:pass@host:port)")
    ap.add_argument("--count", default=1, type=int, help="Количество аккаунтов")
    ap.add_argument("--proton-only", action="store_true", help="Только регистрация Proton (без Steam)")
    ap.add_argument("--steam-only", action="store_true", help="Только регистрация Steam (Chrome уже открыт с Proton)")
    ap.add_argument("--email", default=None, help="Email для Steam регистрации (user@proton.me)")
    args = ap.parse_args()

    if args.steam_only:
        # Только регистрация Steam через Playwright
        steam = SteamPlaywright(proxy=args.proxy)

        try:
            email = args.email or f"{gen_username()}@proton.me"
            steam_login = gen_username()
            steam_password = gen_password()

            print(f"\n── Steam регистрация (Playwright) ──")
            print(f"  Email: {email}")
            print(f"  Login: {steam_login} | Pass: {steam_password}")

            # Шаг 1: Открыть Steam, заполнить email, решить captcha
            result = steam.register(email, steam_login, steam_password)

            if result.get("ok") and result.get("stage") == "email_sent":
                creation_id = result.get("creation_id", "")
                print(f"\n  ⏳ Email отправлен на {email}")
                print(f"  Подтверди email (кликни по ссылке в Proton), потом нажми Enter...")
                input()

                # Шаг 2: Создать аккаунт
                result2 = steam.complete_after_email_verification(
                    steam_login, steam_password, creation_id)
                if result2["ok"]:
                    print(f"  ✓ Steam: {steam_login} | SteamID: {result2.get('steam_id', '')}")
                else:
                    print(f"  ✗ {result2.get('msg')}")
            elif result.get("ok"):
                print(f"  ✓ {result.get('msg')}")
            else:
                print(f"  ✗ {result.get('msg')}")

        finally:
            # Не закрываем браузер — оставляем для проверки
            logger.info("[Pipeline] Playwright браузер остаётся открытым")

    elif args.proton_only:
        # Только регистрация Proton для тестирования CV
        launcher = ChromeLauncher()
        chrome = launcher.launch(proxy=args.proxy)
        time.sleep(3)

        try:
            human = HumanBehavior()
            screen = ScreenAutomation(chrome, launcher, human)
            proton = ProtonCV(screen, human)

            for i in range(args.count):
                username = gen_username()
                password = gen_password()
                print(f"\n── Proton аккаунт {i + 1}/{args.count} ──")
                print(f"  User: {username}@proton.me | Pass: {password}")

                result = proton.register(username, password)
                if result["ok"]:
                    print(f"  ✓ {result['email']}")
                else:
                    print(f"  ✗ {result.get('msg', 'unknown error')}")

                if i < args.count - 1:
                    wait = random.uniform(120, 300)
                    print(f"  Пауза {wait:.0f}с...")
                    time.sleep(wait)
        finally:
            logger.info(f"[Pipeline] Chrome остаётся открытым (PID={chrome.pid})")
    else:
        pipeline = FullRegistrationPipeline(proxy=args.proxy)
        pipeline.run_batch(count=args.count)


if __name__ == "__main__":
    main()
