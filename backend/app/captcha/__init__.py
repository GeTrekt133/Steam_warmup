"""
hCaptcha solvers package.

Available solvers:
- ChallengerSolver: Playwright + Gemini AI (hcaptcha-challenger library)
- HCaptchaSolver:   Groq Vision AI + Playwright HSW (API-based, no browser UI)
- find_line_endpoints: OpenCV solver for "click on line ends" captcha type
"""

from .challenger_wrapper import ChallengerSolver
from .hcaptcha_solver import HCaptchaSolver
from .solve_line_ends import find_line_endpoints

__all__ = ["ChallengerSolver", "HCaptchaSolver", "find_line_endpoints"]
