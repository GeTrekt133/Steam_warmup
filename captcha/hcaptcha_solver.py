"""
Self-hosted hCaptcha solver using Groq Vision AI.
Supports image_drag_drop, image_label_binary, and text challenges.
"""

import hashlib
import json
import logging
import time
import base64
import re
from datetime import datetime
from io import BytesIO

import requests
import jwt

logger = logging.getLogger(__name__)

# Get hCaptcha version
def get_hcaptcha_version():
    api_js = requests.get('https://hcaptcha.com/1/api.js?render=explicit&onload=hcaptchaOnLoad', timeout=15).text
    versions = re.findall(r'v1/([A-Za-z0-9]+)/static', api_js)
    return versions[1] if len(versions) > 1 else versions[0]

HCAPTCHA_VERSION = None

def version():
    global HCAPTCHA_VERSION
    if HCAPTCHA_VERSION is None:
        HCAPTCHA_VERSION = get_hcaptcha_version()
    return HCAPTCHA_VERSION


class GroqVision:
    """Uses Groq API with Llama 4 Scout for image analysis."""

    def __init__(self, api_key):
        self.api_key = api_key
        self.model = "meta-llama/llama-4-maverick-17b-128e-instruct"
        self.host = "https://api.groq.com/openai/v1/chat/completions"

    def ask(self, prompt, image_urls=None, image_b64s=None):
        content = [{"type": "text", "text": prompt}]
        if image_urls:
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        if image_b64s:
            for b64 in image_b64s:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        resp = requests.post(self.host, json={
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 300
        }, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)

        data = resp.json()
        if "error" in data:
            logger.error("Groq error: %s", data["error"])
            return None
        return data["choices"][0]["message"]["content"]


class HSWGenerator:
    """Generates HSW proof-of-work tokens using Playwright."""

    def __init__(self):
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)

    def generate(self, req_token, host):
        self._ensure_browser()
        try:
            context = self._browser.new_context(bypass_csp=True)
            page = context.new_page()
            decoded = jwt.decode(req_token, options={"verify_signature": False})
            url = decoded.get('l', '')
            if not url.startswith("http"):
                url = "https://newassets.hcaptcha.com" + url

            import httpx
            hsw_js = httpx.get(f"{url}/hsw.js", timeout=15).text

            page.goto(f"https://{host}")
            page.add_script_tag(content='Object.defineProperty(navigator,"webdriver",{"get":()=>false})')
            page.add_script_tag(content=hsw_js)
            result = page.evaluate(f'hsw("{req_token}")')
            page.close()
            context.close()
            return str(result)
        except Exception as e:
            logger.error("HSW generation failed: %s", e)
            return None

    def close(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()


def _simple_motion_data(user_agent, href):
    """Generate minimal motion data without scipy dependency."""
    import random
    import string

    screen_w, screen_h = 1920, 1080
    now_ms = int(time.time() * 1000)
    widget_id = '0' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

    mm = []
    x, y = random.randint(100, 800), random.randint(100, 600)
    for i in range(5):
        x += random.randint(-20, 50)
        y += random.randint(-20, 50)
        mm.append([x, y, now_ms + i * 50])

    return {
        'st': now_ms - 2000,
        'mm': mm,
        'mm-mp': 50.0,
        'md': [mm[-1][:-1] + [now_ms]],
        'md-mp': 0,
        'mu': [mm[-1][:-1] + [now_ms + 50]],
        'mu-mp': 0,
        'v': 1,
        'topLevel': {
            'inv': False,
            'st': now_ms - 3000,
            'sc': {
                'availWidth': screen_w, 'availHeight': screen_h,
                'width': screen_w, 'height': screen_h,
                'colorDepth': 24, 'pixelDepth': 24,
                'top': 0, 'left': 0, 'availTop': 0, 'availLeft': 0
            },
            'nv': {
                'pdfViewerEnabled': True, 'doNotTrack': 'unspecified',
                'maxTouchPoints': 0, 'vendor': '', 'vendorSub': '',
                'cookieEnabled': True, 'webdriver': False,
                'hardwareConcurrency': random.choice([4, 8, 12, 16]),
                'userAgent': user_agent,
                'language': 'en-US', 'languages': ['en-US', 'en'],
                'onLine': True,
                'plugins': ['internal-pdf-viewer'] * 5
            },
            'dr': '', 'exec': False,
            'wn': [[screen_w, screen_h, 1, now_ms - 3000]],
            'wn-mp': 0,
            'xy': [[0, 0, 1, now_ms - 3000]],
            'xy-mp': 0,
            'mm': mm,
            'mm-mp': 50.0
        },
        'session': [],
        'widgetList': [widget_id],
        'widgetId': widget_id,
        'href': href,
        'prev': {'escaped': False, 'passed': False, 'expiredChallenge': False, 'expiredResponse': False}
    }


def _check_motion_data():
    """Generate minimal check motion data."""
    import random
    now_ms = int(time.time() * 1000)
    mm = []
    x, y = 200, 200
    for i in range(8):
        x += random.randint(-10, 30)
        y += random.randint(-10, 30)
        mm.append([x, y, now_ms + i * 40])

    return {
        'st': now_ms,
        'dct': now_ms,
        'mm': mm,
        'mm-mp': 40.0,
        'md': [mm[-1][:-1] + [now_ms + 350]],
        'md-mp': 0,
        'mu': [mm[-1][:-1] + [now_ms + 400]],
        'mu-mp': 0,
        'v': 1,
        'topLevel': {
            'inv': False, 'st': now_ms - 1000,
            'sc': {'availWidth': 1920, 'availHeight': 1080, 'width': 1920, 'height': 1080,
                   'colorDepth': 24, 'pixelDepth': 24},
            'nv': {'webdriver': False, 'hardwareConcurrency': 8},
            'mm': mm, 'mm-mp': 40.0
        }
    }


class HCaptchaSolver:
    """
    Solves hCaptcha challenges using Groq Vision AI + Playwright HSW.
    Drop-in replacement for captcha service classes in steamreg.py.
    """

    USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36')

    def __init__(self, groq_api_key, host=None):
        self.api_key = groq_api_key
        self.vision = GroqVision(groq_api_key)
        self.hsw_gen = HSWGenerator()
        self.proxies = []  # list of proxy strings: "http://user:pass@ip:port"
        self._proxy_index = 0

    def set_proxies(self, proxy_list):
        """Set list of proxies to rotate through on each attempt."""
        self.proxies = proxy_list if proxy_list else []
        self._proxy_index = 0

    def _next_proxy(self):
        """Get next proxy from rotation, or None."""
        if not self.proxies:
            return None
        proxy = self.proxies[self._proxy_index % len(self.proxies)]
        self._proxy_index += 1
        return proxy

    def get_balance(self):
        return "Groq (free)"

    def _create_session(self, proxy=None):
        try:
            from tls_client import Session
            session = Session(client_identifier="firefox_121", random_tls_extension_order=True)
        except ImportError:
            session = requests.Session()

        session.headers = {
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
            "accept-language": "en-US;q=0.9"
        }
        if proxy:
            session.proxies = {
                "http": proxy,
                "https": proxy
            }
            logger.info("Using proxy: %s", proxy.split("@")[-1] if "@" in proxy else proxy)
        return session

    def generate_hcaptcha(self, sitekey):
        """Solve hCaptcha and return the token directly. Returns (task_data,) for resolve_captcha."""
        return {"sitekey": sitekey, "host": "store.steampowered.com"}

    def resolve_captcha(self, task_data, max_attempts=5):
        """Actually solve the captcha. Returns (status, token, cost)."""
        for attempt in range(max_attempts):
            try:
                proxy = self._next_proxy()
                return self._try_solve(task_data, proxy=proxy)
            except Exception as e:
                logger.warning("hCaptcha attempt %d/%d failed: %s", attempt + 1, max_attempts, e)
                if attempt == max_attempts - 1:
                    raise
                time.sleep(2)

    def _try_solve(self, task_data, proxy=None):
        sitekey = task_data["sitekey"]
        host = task_data["host"]
        session = self._create_session(proxy=proxy)
        ver = version()

        # Step 1: Get site config
        sc = session.post("https://hcaptcha.com/checksiteconfig", params={
            'v': ver, 'sitekey': sitekey, 'host': host, 'sc': '1', 'swa': '1', 'spst': '1'
        })
        siteconfig = sc.json()
        logger.info("hCaptcha siteconfig OK")

        motion = _simple_motion_data(self.USER_AGENT, f"https://{host}")

        # Step 2: Get captcha challenge (first request)
        hsw1 = self.hsw_gen.generate(siteconfig['c']['req'], host)
        if not hsw1:
            raise Exception("HSW token generation failed")

        data1 = {
            'v': ver, 'sitekey': sitekey, 'host': host, 'hl': 'en',
            'motionData': json.dumps(motion),
            'pdc': {"s": round(datetime.now().timestamp() * 1000), "n": 0, "p": 0, "gcs": 10},
            'n': hsw1, 'c': json.dumps(siteconfig['c']), 'pst': False
        }
        cap1 = session.post(f"https://hcaptcha.com/getcaptcha/{sitekey}", data=data1).json()
        logger.info("hCaptcha challenge 1 received, type: %s", cap1.get('request_type', 'unknown'))

        # Step 3: Get captcha challenge (second request - accessibility text mode)
        if 'c' not in cap1:
            raise Exception("hCaptcha challenge 1 failed: %s" % cap1)

        hsw2 = self.hsw_gen.generate(cap1['c']['req'], host)
        data2 = {
            'v': ver, 'sitekey': sitekey, 'host': host, 'hl': 'en',
            'a11y_tfe': 'true',
            'action': 'challenge-refresh',
            'old_ekey': cap1.get('key', ''),
            'extraData': cap1,
            'motionData': json.dumps(motion),
            'pdc': {"s": round(datetime.now().timestamp() * 1000), "n": 0, "p": 0, "gcs": 10},
            'n': hsw2, 'c': json.dumps(cap1['c']), 'pst': False
        }
        cap2 = session.post(f"https://hcaptcha.com/getcaptcha/{sitekey}", data=data2).json()
        request_type = cap2.get('request_type', 'unknown')
        logger.info("hCaptcha challenge 2 received, type: %s", request_type)

        if 'tasklist' not in cap2:
            raise Exception("hCaptcha no tasklist in challenge: %s" % json.dumps(cap2)[:300])

        # Step 4: Solve based on type
        answers = {}
        question = cap2.get('requester_question', {}).get('en', '')

        if request_type == 'image_drag_drop':
            answers = self._solve_drag_drop(cap2, question)
        elif request_type in ('image_label_binary', 'image_label_area_select'):
            answers = self._solve_image_label(cap2, question)
        else:
            # Try text-based
            answers = self._solve_text(cap2)

        # Step 5: Submit answers
        hsw3 = self.hsw_gen.generate(cap2['c']['req'], host)
        submit = session.post(
            f"https://api.hcaptcha.com/checkcaptcha/{sitekey}/{cap2['key']}",
            json={
                'answers': answers,
                'c': json.dumps(cap2['c']),
                'job_mode': request_type,
                'motionData': json.dumps(_check_motion_data()),
                'n': hsw3,
                'serverdomain': host,
                'sitekey': sitekey,
                'v': ver,
            }
        )

        result = submit.json()
        if result.get('pass'):
            token = result['generated_pass_UUID']
            logger.info("hCaptcha solved! Token: %s...", token[:50])
            return "OK", token, 0
        else:
            logger.error("hCaptcha failed: %s", json.dumps(result)[:300])
            raise Exception("hCaptcha solve failed")

    def _solve_drag_drop(self, cap, question):
        """Solve drag-and-drop: find shadows with OpenCV, match with AI."""
        import cv2
        import numpy as np

        answers = {}
        for task in cap['tasklist']:
            task_key = task['task_key']
            bg_url = task['datapoint_uri']
            entities = task.get('entities', [])

            # Download background
            bg_data = requests.get(bg_url, timeout=15).content
            bg_arr = np.frombuffer(bg_data, np.uint8)
            bg_img = cv2.imdecode(bg_arr, cv2.IMREAD_UNCHANGED)
            bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
            bg_h, bg_w = bg_gray.shape[:2]

            # Find shadow blobs (dark regions)
            _, shadow_mask = cv2.threshold(bg_gray, 80, 255, cv2.THRESH_BINARY_INV)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            shadow_mask = cv2.morphologyEx(shadow_mask, cv2.MORPH_CLOSE, kernel)
            shadow_mask = cv2.morphologyEx(shadow_mask, cv2.MORPH_OPEN, kernel)

            contours, _ = cv2.findContours(shadow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Filter contours by size (shadows should be reasonably large)
            shadow_centers = []
            min_area = (bg_w * bg_h) * 0.005  # at least 0.5% of image
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < min_area:
                    continue
                M = cv2.moments(cnt)
                if M["m00"] == 0:
                    continue
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                shadow_centers.append((cx, cy, area))

            shadow_centers.sort(key=lambda s: s[2], reverse=True)
            logger.info("Found %d shadow regions in background (%dx%d)", len(shadow_centers), bg_w, bg_h)
            for i, (cx, cy, area) in enumerate(shadow_centers):
                logger.info("  Shadow %d: center=(%d, %d) area=%d", i, cx, cy, int(area))

            # Download entity images
            entity_b64s = []
            for ent in entities:
                ent_data = requests.get(ent['entity_uri'], timeout=15).content
                entity_b64s.append(base64.b64encode(ent_data).decode())

            bg_b64 = base64.b64encode(bg_data).decode()

            # Use AI to match entities to shadows
            shadow_desc = "\n".join(
                f"shadow_{i}: center at ({cx}, {cy})"
                for i, (cx, cy, _) in enumerate(shadow_centers[:8])
            )

            prompt = (
                f"You are solving a captcha. Task: \"{question}\"\n\n"
                f"Image 1 is the background with shadow silhouettes.\n"
            )
            for i in range(len(entities)):
                prompt += f"Image {i+2} is entity_{i} (a draggable object).\n"
            prompt += (
                f"\nI detected these shadow positions in the background:\n{shadow_desc}\n\n"
                f"Match each entity to its correct shadow by shape/silhouette.\n"
                f"Reply ONLY in this exact format, nothing else:\n"
            )
            for i in range(len(entities)):
                prompt += f"entity_{i}: shadow_N\n"

            all_b64 = [bg_b64] + entity_b64s
            response = self.vision.ask(prompt, image_b64s=all_b64)
            logger.info("AI matching response: %s", response)

            # Parse AI response and map entities to shadow centers
            entity_answers = {}
            if response:
                for line in response.strip().split('\n'):
                    match = re.search(r'entity_(\d+)\s*:\s*shadow_(\d+)', line)
                    if match:
                        ent_idx = int(match.group(1))
                        shadow_idx = int(match.group(2))
                        if ent_idx < len(entities) and shadow_idx < len(shadow_centers):
                            cx, cy, _ = shadow_centers[shadow_idx]
                            entity_answers[entities[ent_idx]['entity_id']] = {'x': cx, 'y': cy}

            # Fallback: if AI failed, use template matching
            if len(entity_answers) < len(entities):
                logger.warning("AI matching incomplete (%d/%d), using template matching fallback",
                             len(entity_answers), len(entities))
                used = set(entity_answers.keys())
                used_shadows = set()
                for eid, pos in entity_answers.items():
                    for i, (cx, cy, _) in enumerate(shadow_centers):
                        if abs(cx - pos['x']) < 20 and abs(cy - pos['y']) < 20:
                            used_shadows.add(i)
                            break

                for ent in entities:
                    if ent['entity_id'] in used:
                        continue
                    # Assign next unused shadow
                    for i, (cx, cy, _) in enumerate(shadow_centers):
                        if i not in used_shadows:
                            entity_answers[ent['entity_id']] = {'x': cx, 'y': cy}
                            used_shadows.add(i)
                            break

            answers[task_key] = entity_answers

        return answers

    def _solve_image_label(self, cap, question):
        """Solve image label (select matching images) challenges."""
        answers = {}
        for task in cap['tasklist']:
            task_key = task['task_key']
            img_url = task.get('datapoint_uri', '')

            if img_url:
                prompt = (
                    f"Question: {question}\n"
                    f"Look at this image. Does it match the question? "
                    f"Reply ONLY 'true' or 'false'."
                )
                response = self.vision.ask(prompt, image_urls=[img_url])
                is_match = response and 'true' in response.lower()
            else:
                is_match = False

            answers[task_key] = str(is_match).lower()

        return answers

    def _solve_text(self, cap):
        """Solve text-based challenges using AI."""
        answers = {}
        for task in cap['tasklist']:
            task_key = task['task_key']
            q = task.get('datapoint_text', {}).get('en', '')
            if q:
                prompt = f"Strictly respond with only one single word, number, or short phrase. Question: {q}"
                response = self.vision.ask(prompt)
                answers[task_key] = {'text': response.strip() if response else 'yes'}
            else:
                answers[task_key] = {'text': 'yes'}
        return answers

    def generate_captcha_img(self, captcha_img):
        raise Exception("HCaptchaSolver does not support image captcha")

    def report_bad(self, task_id):
        pass

    def report_good(self, task_id):
        pass

    def close(self):
        self.hsw_gen.close()
