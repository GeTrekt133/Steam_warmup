"""
Captcha solvers package.

Available solvers:
- ChallengerSolver: Playwright + Gemini AI (hcaptcha-challenger library)
- HCaptchaSolver:   Groq Vision AI + Playwright HSW (API-based, no browser UI)
- find_line_endpoints: OpenCV solver for "click on line ends" captcha type
- PuzzleSolver: U-Net segmentation for Proton Mail puzzle captcha (no API keys)
"""

from .challenger_wrapper import ChallengerSolver
from .hcaptcha_solver import HCaptchaSolver
from .solve_line_ends import find_line_endpoints
from .solve_puzzle import PuzzleSolver

__all__ = [
    "ChallengerSolver",
    "HCaptchaSolver",
    "find_line_endpoints",
    "PuzzleSolver",
]
