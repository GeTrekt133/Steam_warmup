"""
Captcha Benchmark — тестирование провайдеров капч.

Standalone-скрипт. Запускай на любом компе:
    pip install httpx
    python captcha_benchmark.py --once              # один раунд тестов
    python captcha_benchmark.py --loop 30           # раз в 30 минут
    python captcha_benchmark.py --provider capsolver # только CapSolver
    python captcha_benchmark.py --provider ezcaptcha # только EzCaptcha

Результаты сохраняются в captcha_benchmark_results.jsonl
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Установи httpx: pip install httpx")
    sys.exit(1)


# ── Конфигурация ─────────────────────────────────────────────

STEAM_HCAPTCHA_SITEKEY = "f5561ba9-8f1e-40ca-9b5b-a0b3f719ef34"
STEAM_PAGE_URL = "https://store.steampowered.com/join"

OUTLOOK_FUNCAPTCHA_KEY = "B7D8911C-5CC8-A9A3-35B0-554ACEE604DA"
OUTLOOK_PAGE_URL = "https://signup.live.com/signup"

RESULTS_FILE = "captcha_benchmark_results.jsonl"


# ── CapSolver (Steam hCaptcha) ───────────────────────────────

def test_capsolver(api_key: str) -> dict:
    """Тест CapSolver на Steam hCaptcha."""
    result = {
        "provider": "capsolver",
        "captcha_type": "hcaptcha",
        "target": "steam",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "elapsed_sec": 0,
        "error": None,
        "token_preview": None,
        "balance": None,
    }

    try:
        # Проверяем баланс
        bal_resp = httpx.post(
            "https://api.capsolver.com/getBalance",
            json={"clientKey": api_key},
            timeout=10,
        )
        bal_data = bal_resp.json()
        if bal_data.get("errorId", 0) == 0:
            result["balance"] = bal_data.get("balance")

        # Создаём задачу
        start = time.monotonic()
        resp = httpx.post(
            "https://api.capsolver.com/createTask",
            json={
                "clientKey": api_key,
                "task": {
                    "type": "HCaptchaTaskProxyLess",
                    "websiteURL": STEAM_PAGE_URL,
                    "websiteKey": STEAM_HCAPTCHA_SITEKEY,
                },
            },
            timeout=30,
        )
        data = resp.json()

        if data.get("errorId", 0) != 0:
            result["error"] = f"{data.get('errorCode')}: {data.get('errorDescription')}"
            result["elapsed_sec"] = round(time.monotonic() - start, 1)
            return result

        task_id = data.get("taskId")
        if not task_id:
            result["error"] = f"No taskId: {data}"
            result["elapsed_sec"] = round(time.monotonic() - start, 1)
            return result

        print(f"  [capsolver] Задача создана: {task_id}")

        # Polling
        time.sleep(5)
        while time.monotonic() - start < 180:
            resp = httpx.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=30,
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                result["error"] = data.get("errorDescription")
                break

            if data.get("status") == "ready":
                solution = data.get("solution", {})
                token = solution.get("gRecaptchaResponse") or solution.get("token") or ""
                result["success"] = True
                result["token_preview"] = token[:60] + "..." if len(token) > 60 else token
                break

            if data.get("status") == "processing":
                time.sleep(3)
                continue

            result["error"] = f"Unexpected status: {data.get('status')}"
            break
        else:
            result["error"] = "Timeout 180s"

        result["elapsed_sec"] = round(time.monotonic() - start, 1)

    except Exception as e:
        result["error"] = str(e)

    return result


# ── EzCaptcha (Outlook FunCaptcha) ───────────────────────────

def test_ezcaptcha(api_key: str) -> dict:
    """Тест EzCaptcha на Outlook FunCaptcha."""
    result = {
        "provider": "ezcaptcha",
        "captcha_type": "funcaptcha",
        "target": "outlook",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "elapsed_sec": 0,
        "error": None,
        "token_preview": None,
        "balance": None,
    }

    try:
        # Проверяем баланс
        try:
            bal_resp = httpx.post(
                "https://api.ez-captcha.com/getBalance",
                json={"clientKey": api_key},
                timeout=10,
            )
            bal_data = bal_resp.json()
            if bal_data.get("errorId", 0) == 0:
                result["balance"] = bal_data.get("balance")
        except Exception:
            pass

        # Создаём задачу
        start = time.monotonic()
        resp = httpx.post(
            "https://api.ez-captcha.com/createTask",
            json={
                "clientKey": api_key,
                "task": {
                    "type": "FunCaptchaTaskProxyless",
                    "websiteURL": OUTLOOK_PAGE_URL,
                    "websitePublicKey": OUTLOOK_FUNCAPTCHA_KEY,
                },
            },
            timeout=30,
        )
        data = resp.json()

        if data.get("errorId", 0) != 0:
            result["error"] = f"{data.get('errorCode')}: {data.get('errorDescription')}"
            result["elapsed_sec"] = round(time.monotonic() - start, 1)
            return result

        task_id = data.get("taskId")
        if not task_id:
            result["error"] = f"No taskId: {data}"
            result["elapsed_sec"] = round(time.monotonic() - start, 1)
            return result

        print(f"  [ezcaptcha] Задача создана: {task_id}")

        # Polling
        time.sleep(10)
        while time.monotonic() - start < 240:
            resp = httpx.post(
                "https://api.ez-captcha.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=30,
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                result["error"] = data.get("errorDescription")
                break

            if data.get("status") == "ready":
                token = data.get("solution", {}).get("token", "")
                result["success"] = True
                result["token_preview"] = token[:60] + "..." if len(token) > 60 else token
                break

            if data.get("status") == "processing":
                time.sleep(5)
                continue

            result["error"] = f"Unexpected status: {data.get('status')}"
            break
        else:
            result["error"] = "Timeout 240s"

        result["elapsed_sec"] = round(time.monotonic() - start, 1)

    except Exception as e:
        result["error"] = str(e)

    return result


# ── 2Captcha (Steam hCaptcha — для сравнения) ────────────────

def test_2captcha_hcaptcha(api_key: str) -> dict:
    """Тест 2Captcha на Steam hCaptcha."""
    result = {
        "provider": "2captcha",
        "captcha_type": "hcaptcha",
        "target": "steam",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "elapsed_sec": 0,
        "error": None,
        "token_preview": None,
        "balance": None,
    }

    try:
        # Баланс
        try:
            bal_resp = httpx.get(
                "https://2captcha.com/res.php",
                params={"key": api_key, "action": "getbalance", "json": "1"},
                timeout=10,
            )
            bal_data = bal_resp.json()
            if bal_data.get("status") == 1:
                result["balance"] = float(bal_data.get("request", 0))
        except Exception:
            pass

        start = time.monotonic()
        resp = httpx.post(
            "https://2captcha.com/in.php",
            data={
                "key": api_key,
                "method": "hcaptcha",
                "sitekey": STEAM_HCAPTCHA_SITEKEY,
                "pageurl": STEAM_PAGE_URL,
                "json": "1",
            },
            timeout=30,
        )
        data = resp.json()

        if data.get("status") != 1:
            result["error"] = data.get("request")
            result["elapsed_sec"] = round(time.monotonic() - start, 1)
            return result

        task_id = data["request"]
        print(f"  [2captcha] Задача создана: {task_id}")

        time.sleep(15)
        while time.monotonic() - start < 180:
            resp = httpx.get(
                "https://2captcha.com/res.php",
                params={"key": api_key, "action": "get", "id": task_id, "json": "1"},
                timeout=30,
            )
            data = resp.json()

            if data.get("status") == 1:
                token = data["request"]
                result["success"] = True
                result["token_preview"] = token[:60] + "..."
                break

            if data.get("request") == "CAPCHA_NOT_READY":
                time.sleep(5)
                continue

            result["error"] = data.get("request")
            break
        else:
            result["error"] = "Timeout 180s"

        result["elapsed_sec"] = round(time.monotonic() - start, 1)

    except Exception as e:
        result["error"] = str(e)

    return result


# ── Запуск ───────────────────────────────────────────────────

def run_benchmark(providers: list[str], keys: dict) -> list[dict]:
    """Один раунд бенчмарка."""
    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Captcha Benchmark — {timestamp}")
    print(f"{'='*60}")

    for provider in providers:
        key = keys.get(provider)
        if not key:
            print(f"\n  [{provider}] ПРОПУЩЕН — нет API ключа")
            continue

        print(f"\n  [{provider}] Тестирую...")

        if provider == "capsolver":
            r = test_capsolver(key)
        elif provider == "ezcaptcha":
            r = test_ezcaptcha(key)
        elif provider == "2captcha":
            r = test_2captcha_hcaptcha(key)
        else:
            continue

        status = "OK" if r["success"] else "FAIL"
        print(f"  [{provider}] {status} | {r['elapsed_sec']}s | balance={r['balance']}")
        if r["error"]:
            print(f"  [{provider}] Ошибка: {r['error']}")
        if r["token_preview"]:
            print(f"  [{provider}] Токен: {r['token_preview']}")

        results.append(r)

    return results


def save_results(results: list[dict], filepath: str):
    """Сохранить результаты в JSONL."""
    with open(filepath, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def print_summary(filepath: str):
    """Вывести сводку по всем результатам."""
    if not Path(filepath).exists():
        return

    lines = Path(filepath).read_text("utf-8").strip().splitlines()
    if not lines:
        return

    stats: dict[str, dict] = {}
    for line in lines:
        try:
            r = json.loads(line)
            key = r["provider"]
            if key not in stats:
                stats[key] = {"total": 0, "success": 0, "times": [], "target": r.get("target", "")}
            stats[key]["total"] += 1
            if r["success"]:
                stats[key]["success"] += 1
                stats[key]["times"].append(r["elapsed_sec"])
        except Exception:
            pass

    print(f"\n{'='*60}")
    print("  СВОДКА")
    print(f"{'='*60}")
    for provider, s in stats.items():
        rate = s["success"] / s["total"] * 100 if s["total"] > 0 else 0
        avg_time = sum(s["times"]) / len(s["times"]) if s["times"] else 0
        print(f"  {provider} ({s['target']}): {s['success']}/{s['total']} ({rate:.0f}%) | avg {avg_time:.1f}s")
    print()


def main():
    parser = argparse.ArgumentParser(description="Captcha Benchmark")
    parser.add_argument("--once", action="store_true", help="Один раунд тестов")
    parser.add_argument("--loop", type=int, metavar="MINUTES", help="Повторять каждые N минут")
    parser.add_argument("--count", type=int, default=1, help="Количество тестов за раунд (по умолчанию 1)")
    parser.add_argument("--provider", type=str, help="Тестировать только указанный провайдер (capsolver, ezcaptcha, 2captcha)")
    parser.add_argument("--output", type=str, default=RESULTS_FILE, help="Файл для результатов")

    # API ключи — из аргументов или переменных окружения
    parser.add_argument("--capsolver-key", type=str, default=os.environ.get("CAPSOLVER_API_KEY", ""))
    parser.add_argument("--ezcaptcha-key", type=str, default=os.environ.get("EZCAPTCHA_API_KEY", ""))
    parser.add_argument("--2captcha-key", type=str, default=os.environ.get("TWOCAPTCHA_API_KEY", ""))

    args = parser.parse_args()

    keys = {
        "capsolver": args.capsolver_key,
        "ezcaptcha": args.ezcaptcha_key,
        "2captcha": getattr(args, "2captcha_key", ""),
    }

    # Определяем какие провайдеры тестировать
    if args.provider:
        providers = [args.provider]
    else:
        providers = [p for p in ["capsolver", "ezcaptcha", "2captcha"] if keys.get(p)]

    if not providers:
        print("Нет API ключей. Укажи через аргументы или переменные окружения:")
        print("  --capsolver-key KEY   или   CAPSOLVER_API_KEY=KEY")
        print("  --ezcaptcha-key KEY   или   EZCAPTCHA_API_KEY=KEY")
        print("  --2captcha-key KEY    или   TWOCAPTCHA_API_KEY=KEY")
        sys.exit(1)

    print(f"Провайдеры: {', '.join(providers)}")
    print(f"Тестов за раунд: {args.count}")
    print(f"Результаты: {args.output}")

    if args.once or not args.loop:
        for _ in range(args.count):
            results = run_benchmark(providers, keys)
            save_results(results, args.output)
        print_summary(args.output)

    elif args.loop:
        print(f"Режим цикла: каждые {args.loop} мин")
        try:
            while True:
                for _ in range(args.count):
                    results = run_benchmark(providers, keys)
                    save_results(results, args.output)
                print_summary(args.output)
                print(f"\nСледующий раунд через {args.loop} мин... (Ctrl+C для выхода)")
                time.sleep(args.loop * 60)
        except KeyboardInterrupt:
            print("\nОстановлено.")
            print_summary(args.output)


if __name__ == "__main__":
    main()
