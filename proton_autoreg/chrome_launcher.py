"""
Запуск реального Chrome с чистым профилем и прокси.
Никакого CDP/Playwright/Selenium — чистый subprocess.
"""
import os
import sys
import time
import shutil
import tempfile
import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChromeInstance:
    """Запущенный инстанс Chrome."""
    pid: int
    process: subprocess.Popen
    profile_dir: Path
    window_title: str  # для поиска окна
    proxy: str | None = None
    _keep_profile: bool = False


class ChromeLauncher:
    """Управление инстансами Chrome без CDP."""

    # Стандартные пути Chrome на Windows
    CHROME_PATHS = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        # Edge как fallback
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]

    def __init__(self):
        self._chrome_path = self._find_chrome()
        self._instances: dict[int, ChromeInstance] = {}

    def _find_chrome(self) -> str:
        """Находит исполняемый файл Chrome/Edge."""
        # Проверяем реестр (Windows)
        if sys.platform == "win32":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
                )
                path, _ = winreg.QueryValueEx(key, "")
                winreg.CloseKey(key)
                if os.path.isfile(path):
                    logger.info(f"Chrome найден (реестр): {path}")
                    return path
            except Exception:
                pass

        # Проверяем стандартные пути
        for p in self.CHROME_PATHS:
            if os.path.isfile(p):
                logger.info(f"Chrome найден: {p}")
                return p

        raise FileNotFoundError(
            "Chrome/Edge не найден. Установите Google Chrome или Microsoft Edge."
        )

    @staticmethod
    def _set_system_layout_english() -> None:
        """Переключить системную раскладку на English (US) до запуска Chrome."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # Загружаем и активируем EN-US раскладку системно
            hkl = user32.LoadKeyboardLayoutW("00000409", 1)  # KLF_ACTIVATE
            user32.ActivateKeyboardLayout(hkl, 0x00000100)   # KLF_SETFORPROCESS
            logger.info("Системная раскладка: EN-US")
        except Exception as e:
            logger.warning(f"Не удалось переключить раскладку: {e}")

    def launch(
        self,
        proxy: str | None = None,
        keep_profile: bool = False,
        window_size: tuple[int, int] = (1280, 900),
        window_position: tuple[int, int] = (0, 0),
        lang: str = "en-US",
        start_url: str = "about:blank",
    ) -> ChromeInstance:
        """
        Запускает Chrome с чистым профилем.

        Args:
            proxy: Прокси в формате user:pass@host:port или host:port
            keep_profile: Не удалять профиль после закрытия
            window_size: Размер окна (width, height)
            window_position: Позиция окна (x, y)
            lang: Язык браузера
            start_url: Стартовая страница
        """
        # Переключаем системную раскладку на EN-US до запуска Chrome
        self._set_system_layout_english()

        # Создаём temp профиль
        profile_dir = Path(tempfile.mkdtemp(prefix="chrome_cv_"))
        logger.info(f"Профиль: {profile_dir}")

        # Уникальный заголовок окна для поиска
        window_title = f"CV_Chrome_{int(time.time() * 1000) % 100000}"

        # Формируем аргументы Chrome
        args = [
            self._chrome_path,
            f"--user-data-dir={profile_dir}",
            f"--window-size={window_size[0]},{window_size[1]}",
            f"--window-position={window_position[0]},{window_position[1]}",
            f"--lang={lang}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-translate",
            "--disable-extensions",
            "--disable-component-update",
            "--disable-default-apps",
            # НЕ добавляем: --remote-debugging-port, --enable-automation, --headless
        ]

        # Прокси
        proxy_server = None
        if proxy:
            proxy = proxy.strip()
            if "@" in proxy:
                # user:pass@host:port → нужна аутентификация через extension
                creds, host = proxy.rsplit("@", 1)
                proxy_server = f"http://{host}"
                # Создаём расширение для прокси-аутентификации
                self._create_proxy_auth_extension(profile_dir, proxy)
                # Включаем загрузку расширений
                args = [a for a in args if a != "--disable-extensions"]
                args.append(f"--load-extension={profile_dir / 'proxy_auth_ext'}")
            else:
                proxy_server = f"http://{proxy}"

            args.append(f"--proxy-server={proxy_server}")

        # Стартовая страница (используем title для поиска окна)
        args.append(start_url)

        logger.info(f"Запуск Chrome: PID ожидается...")
        # CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS — Chrome живёт после завершения Python
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        # Ждём запуска
        time.sleep(2)

        instance = ChromeInstance(
            pid=process.pid,
            process=process,
            profile_dir=profile_dir,
            window_title=window_title,
            proxy=proxy,
            _keep_profile=keep_profile,
        )
        self._instances[process.pid] = instance

        logger.info(f"Chrome запущен: PID={process.pid}")
        return instance

    def _create_proxy_auth_extension(self, profile_dir: Path, proxy: str) -> None:
        """
        Создаёт Chrome-расширение для аутентификации прокси.
        Без этого Chrome покажет popup для ввода логина/пароля.
        """
        creds, host_port = proxy.rsplit("@", 1)
        username, password = creds.split(":", 1)
        host, port = host_port.rsplit(":", 1)

        ext_dir = profile_dir / "proxy_auth_ext"
        ext_dir.mkdir(parents=True, exist_ok=True)

        # manifest.json
        manifest = {
            "version": "1.0.0",
            "manifest_version": 3,
            "name": "Proxy Auth",
            "permissions": ["webRequest", "webRequestAuthProvider"],
            "host_permissions": ["<all_urls>"],
            "background": {"service_worker": "background.js"}
        }

        import json
        (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # background.js
        bg_js = f"""
chrome.webRequest.onAuthRequired.addListener(
    function(details, callbackFn) {{
        callbackFn({{
            authCredentials: {{
                username: "{username}",
                password: "{password}"
            }}
        }});
    }},
    {{urls: ["<all_urls>"]}},
    ["asyncBlocking"]
);
"""
        (ext_dir / "background.js").write_text(bg_js)
        logger.info(f"Proxy auth extension создана: {ext_dir}")

    def get_window_rect(self, instance: ChromeInstance) -> tuple[int, int, int, int] | None:
        """
        Возвращает (x, y, width, height) окна Chrome.
        Использует win32gui для точного позиционирования.
        """
        if sys.platform != "win32":
            logger.warning("get_window_rect поддерживается только на Windows")
            return None

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # Callback для EnumWindows
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
            )

            result = [None]

            def enum_callback(hwnd, lparam):
                # Проверяем PID окна
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                if pid.value == instance.pid:
                    # Проверяем что окно видимое
                    if user32.IsWindowVisible(hwnd):
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w > 100 and h > 100:  # игнорируем мелкие окна
                            result[0] = (rect.left, rect.top, w, h)
                            return False  # стоп
                return True

            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

            if result[0]:
                logger.info(f"Окно Chrome: {result[0]}")
            else:
                logger.warning(f"Окно Chrome PID={instance.pid} не найдено")

            return result[0]

        except Exception as e:
            logger.error(f"Ошибка get_window_rect: {e}")
            return None

    def focus_window(self, instance: ChromeInstance) -> bool:
        """Выводит окно Chrome на передний план."""
        if sys.platform != "win32":
            return False

        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
            )

            def enum_callback(hwnd, lparam):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == instance.pid and user32.IsWindowVisible(hwnd):
                    user32.SetForegroundWindow(hwnd)
                    return False
                return True

            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
            return True
        except Exception as e:
            logger.error(f"focus_window ошибка: {e}")
            return False

    def close(self, instance: ChromeInstance) -> None:
        """Закрывает Chrome и удаляет профиль."""
        pid = instance.pid
        logger.info(f"Закрытие Chrome PID={pid}")

        try:
            instance.process.terminate()
            instance.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            instance.process.kill()
            instance.process.wait(timeout=3)
        except Exception as e:
            logger.warning(f"Ошибка при закрытии Chrome: {e}")
            # Принудительно через taskkill
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid), "/T"],
                    capture_output=True, timeout=5
                )
            except Exception:
                pass

        # Удаляем профиль
        if not instance._keep_profile and instance.profile_dir.exists():
            try:
                shutil.rmtree(instance.profile_dir, ignore_errors=True)
                logger.info(f"Профиль удалён: {instance.profile_dir}")
            except Exception as e:
                logger.warning(f"Не удалось удалить профиль: {e}")

        self._instances.pop(pid, None)

    def close_all(self) -> None:
        """Закрывает все запущенные Chrome."""
        for instance in list(self._instances.values()):
            self.close(instance)

    def is_alive(self, instance: ChromeInstance) -> bool:
        """Проверяет что Chrome-процесс жив."""
        return instance.process.poll() is None
