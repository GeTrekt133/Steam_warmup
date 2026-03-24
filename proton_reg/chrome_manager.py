"""
CDP Chrome Manager — запускает реальный Chrome с proxy extension.
Playwright подключается через CDP. Сайт не видит маркеров автоматизации.
"""
import os
import json
import time
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


def find_chrome() -> Path | None:
    candidates = []
    for env in ["ProgramFiles", "ProgramFiles(x86)", "LocalAppData"]:
        base = os.environ.get(env, "")
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for env in ["ProgramFiles", "ProgramFiles(x86)"]:
        base = os.environ.get(env, "")
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for p in candidates:
        if p.exists():
            return p
    result = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("msedge")
    return Path(result) if result else None


def _create_proxy_extension(user, pwd, ip, port, ext_dir):
    """MV2 proxy auth extension."""
    ext_dir.mkdir(parents=True, exist_ok=True)
    (ext_dir / "manifest.json").write_text(json.dumps({
        "version": "1.0",
        "manifest_version": 2,
        "name": "Proxy Auth",
        "permissions": ["proxy", "webRequest", "webRequestBlocking", "<all_urls>"],
        "background": {"scripts": ["bg.js"]},
    }))
    (ext_dir / "bg.js").write_text(f"""
chrome.proxy.settings.set({{value:{{mode:"fixed_servers",rules:{{singleProxy:{{scheme:"http",host:"{ip}",port:parseInt({port})}},bypassList:["localhost"]}}}},scope:"regular"}});
chrome.webRequest.onAuthRequired.addListener(function(d){{return{{authCredentials:{{username:"{user}",password:"{pwd}"}}}}}},{{urls:["<all_urls>"]}},["blocking"]);
""")


class ChromeSession:
    def __init__(self, port, process, profile_dir, browser, context, page):
        self.port = port
        self.process = process
        self.profile_dir = profile_dir
        self.browser = browser
        self.context = context
        self.page = page


class ChromeManager:
    def __init__(self):
        self._sessions = {}
        self._next_port = 9300
        self._pw = None
        self._chrome_path = find_chrome()

    def create_session(self, proxy_str=None):
        if not self._chrome_path:
            raise RuntimeError("Chrome не найден")

        port = self._next_port
        self._next_port += 1
        profile_dir = Path(tempfile.mkdtemp(prefix=f"cdp_{port}_"))

        args = [
            str(self._chrome_path),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--remote-allow-origins=*",
            "--disable-features=ExtensionManifestV2DeprecationWarning",
            "--enable-extensions",
        ]

        proxy_auth = None
        if proxy_str:
            s = proxy_str.strip()
            if "@" in s:
                creds, host = s.rsplit("@", 1)
                user, pwd = creds.split(":", 1)
                proxy_auth = (user, pwd)
            else:
                host = s
            if "://" not in host:
                host = f"http://{host}"
            args.append(f"--proxy-server={host}")

        print(f"  [chrome] Запуск порт {port}...")
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(30):
            try:
                r = requests.get(f"http://localhost:{port}/json/version", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            process.kill()
            raise RuntimeError(f"Chrome не стартовал на порту {port}")

        print(f"  [chrome] CDP готов")

        if not self._pw:
            self._pw = sync_playwright().start()

        browser = self._pw.chromium.connect_over_cdp(f"http://localhost:{port}")

        if proxy_auth:
            user, pwd = proxy_auth
            # Новый context с proxy credentials — Playwright обрабатывает auth
            context = browser.new_context(
                proxy={"server": host, "username": user, "password": pwd}
            )
            page = context.new_page()
        else:
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

        sid = f"session_{port}"
        session = ChromeSession(port, process, profile_dir, browser, context, page)
        session._id = sid
        self._sessions[sid] = session
        print(f"  [chrome] Сессия создана")
        return session

    def close_session(self, session):
        sid = getattr(session, '_id', '')
        try:
            session.browser.close()
        except Exception:
            pass
        try:
            session.process.kill()
            session.process.wait(timeout=5)
        except Exception:
            pass
        try:
            shutil.rmtree(session.profile_dir, ignore_errors=True)
        except Exception:
            pass
        self._sessions.pop(sid, None)
        print(f"  [chrome] Сессия закрыта")

    def close_all(self):
        for s in list(self._sessions.values()):
            self.close_session(s)
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
