"""
Wrapper around hcaptcha-challenger library for solving hCaptcha via Playwright + Gemini AI.
"""
import asyncio
import logging

logger = logging.getLogger('__main__')


class ChallengerSolver:
    """
    Uses hcaptcha-challenger with Playwright browser + Gemini AI to solve hCaptcha.
    Requires a Gemini API key.
    """

    def __init__(self, api_key, host=None):
        self.api_key = api_key
        self._token = None

    def get_balance(self):
        return "Claude AI (hcaptcha-challenger)"

    def generate_captcha_img(self, captcha_img):
        raise Exception("HCaptchaChallenger не поддерживает решение картинок")

    def generate_hcaptcha(self, sitekey):
        logger.info("Starting hcaptcha-challenger with Gemini AI...")
        try:
            token = asyncio.run(self._solve_on_steam(sitekey))
            if token:
                self._token = token
                logger.info("Solved! Token: %s...", token[:50])
                return "challenger_task"
            else:
                logger.error("Failed to solve captcha")
                self._token = None
                return "challenger_task"
        except Exception as e:
            logger.error("hcaptcha-challenger error: %s", e)
            import traceback
            traceback.print_exc()
            self._token = None
            return "challenger_task"

    def resolve_captcha(self, task_id):
        if self._token:
            token = self._token
            self._token = None
            return "OK", token, 0
        return None

    def report_bad(self, task_id):
        pass

    def report_good(self, task_id):
        pass

    async def _solve_on_steam(self, sitekey):
        from playwright.async_api import async_playwright
        from hcaptcha_challenger import AgentV, AgentConfig, CaptchaResponse

        agent_config = AgentConfig(
            GEMINI_API_KEY=self.api_key,
            EXECUTION_TIMEOUT=180,
            RESPONSE_TIMEOUT=45,
            RETRY_ON_FAILURE=True,
            WAIT_FOR_CHALLENGE_VIEW_TO_RENDER_MS=3000,
        )

        token = None
        captured_gid = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
            page = await context.new_page()

            async def intercept_response(response):
                if "refreshcaptcha" in response.url:
                    try:
                        data = await response.json()
                        captured_gid['gid'] = data.get('gid', '')
                    except Exception:
                        pass

            page.on("response", intercept_response)

            try:
                logger.info("Navigating to Steam join page...")
                await page.goto("https://store.steampowered.com/join/", timeout=60000)
                await page.wait_for_timeout(5000)

                checkbox_sel = "iframe[src*='hcaptcha.com'][src*='frame=checkbox']"
                await page.wait_for_selector(checkbox_sel, timeout=20000)
                await page.wait_for_timeout(2000)

                agent = AgentV(page=page, agent_config=agent_config)

                for attempt in range(1, 4):
                    logger.info("Captcha attempt %d/3", attempt)
                    await agent.robotic_arm.click_checkbox()
                    await page.wait_for_timeout(3000)

                    challenge_sel = "iframe[src*='hcaptcha.com'][src*='frame=challenge']"
                    visible = False
                    for i in range(12):
                        try:
                            loc = page.locator(challenge_sel)
                            if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                                visible = True
                                break
                        except Exception:
                            pass
                        await page.wait_for_timeout(1000)

                    if not visible:
                        logger.warning("Challenge not visible, reloading...")
                        await page.reload(timeout=60000)
                        await page.wait_for_timeout(5000)
                        await page.wait_for_selector(checkbox_sel, timeout=20000)
                        await page.wait_for_timeout(2000)
                        agent = AgentV(page=page, agent_config=agent_config)
                        continue

                    logger.info("Challenge visible! Solving with Gemini AI...")
                    try:
                        result = await agent.wait_for_challenge()
                        if agent.cr_list:
                            cr: CaptchaResponse = agent.cr_list[-1]
                            if cr.is_pass and cr.generated_pass_UUID:
                                token = cr.generated_pass_UUID
                                break
                    except Exception as e:
                        logger.error("Solve error: %s", e)

            except Exception as e:
                logger.error("Solver error: %s", e)
            finally:
                await browser.close()

        return token
