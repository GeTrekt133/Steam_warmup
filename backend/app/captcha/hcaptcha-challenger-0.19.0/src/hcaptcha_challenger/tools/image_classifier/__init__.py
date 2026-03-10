# -*- coding: utf-8 -*-
"""
ImageClassifier - 9-grid image classification challenge solver.

Splits the challenge screenshot into 9 individual cell images and classifies
each one separately with a yes/no question for higher accuracy.
"""
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Union, List, Tuple

from PIL import Image
from pydantic import BaseModel
from loguru import logger

from hcaptcha_challenger.models import ImageBinaryChallenge, BoundingBoxCoordinate
from hcaptcha_challenger.tools.internal.base import Reasoner
from hcaptcha_challenger.tools.internal.providers.protocol import ChatProvider
from hcaptcha_challenger.utils import load_desc


class CellAnswer(BaseModel):
    answer: bool


class ImageClassifier(Reasoner[str, ImageBinaryChallenge]):

    description: str = load_desc(Path(__file__).parent / "image_classifier.md")

    EXAMPLES_DIR = Path("d:/steam-autoreg-main/captcha_examples")

    def __init__(
        self,
        gemini_api_key: str,
        model: str = "meta-llama/llama-4-maverick-17b-128e-instruct",
        *,
        provider: ChatProvider | None = None,
        **kwargs,
    ):
        super().__init__(gemini_api_key, model, provider=provider, **kwargs)
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="hcaptcha_cells_"))
        self.EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    def _find_grid_top(self, img: Image.Image) -> int:
        """Find y-coordinate where the colored banner ends and the grid begins."""
        width, height = img.size
        # Scan rows from top: banner is dark/colored, grid bg is light/white
        # Start scanning from 10% to avoid logo area at very top
        for y in range(height // 10, height // 2):
            row_pixels = [img.getpixel((x, y)) for x in range(0, width, 20)]
            avg_brightness = sum((p[0] + p[1] + p[2]) / 3 for p in row_pixels) / len(row_pixels)
            if avg_brightness > 200:
                return max(y - 2, 0)
        return height // 4  # fallback

    def _split_cells(self, img_path: Path) -> List[Tuple[int, int, Path]]:
        """Split the 9-grid area into 9 individual cell images."""
        img = Image.open(img_path).convert("RGB")
        width, height = img.size

        grid_top = self._find_grid_top(img)
        grid_height = height - grid_top
        cell_w = width // 3
        cell_h = grid_height // 3

        logger.debug(f"Grid starts at y={grid_top}, cell size={cell_w}x{cell_h}")

        cells = []
        for row in range(3):
            for col in range(3):
                left = col * cell_w
                top = grid_top + row * cell_h
                cell = img.crop((left, top, left + cell_w, top + cell_h))
                cell_path = self._tmp_dir / f"cell_{row}_{col}.png"
                cell.save(cell_path)
                cells.append((row, col, cell_path))
        return cells

    async def _extract_challenge_text(self, img_path: Path) -> str:
        """Extract challenge text from the banner via vision."""
        img = Image.open(img_path).convert("RGB")
        width, height = img.size
        grid_top = self._find_grid_top(img)
        banner = img.crop((0, 0, width, grid_top))
        banner_path = self._tmp_dir / "banner.png"
        banner.save(banner_path)

        class TextResult(BaseModel):
            text: str

        try:
            result = await self._provider.generate_with_images(
                images=[banner_path],
                user_prompt="Read and return ONLY the text visible in this image, nothing else.",
                description="You are an OCR tool. Return only the exact text from the image.",
                response_schema=TextResult,
            )
            return result.text.strip()
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return ""

    async def _classify_cell(self, cell_path: Path, challenge_text: str, banner_path: Path | None = None) -> bool:
        """Ask the model: does this cell image match the challenge?"""
        try:
            result = await self._provider.generate_with_images(
                images=[cell_path],
                user_prompt=(
                    f'Task: "{challenge_text}"\n'
                    f"Look carefully at this image. Focus ONLY on the main subject/content of the image.\n"
                    f"IMPORTANT: Completely IGNORE any watermarks, semi-transparent text overlays, or faint text patterns on the image — they are NOT part of the actual content.\n"
                    f"Judge only what the real subject of the image is.\n"
                    f'Answer ONLY with JSON: {{"answer": true}} if it matches the task, {{"answer": false}} if not.'
                ),
                description="You are a precise image classifier. Analyze only the actual content/subject of the image, completely ignoring any watermarks or text overlays.",
                response_schema=CellAnswer,
            )
            return result.answer
        except Exception as e:
            logger.warning(f"Cell [{cell_path.stem}] classification failed: {e}")
            return False

    async def __call__(
        self,
        *,
        challenge_screenshot: Union[str, Path],
        challenge_prompt: str | None = None,
        **kwargs,
    ) -> ImageBinaryChallenge:
        """
        Split screenshot into 9 cells and classify each one individually.

        Args:
            challenge_screenshot: Path to the full challenge-view screenshot.
            challenge_prompt: Challenge text (from payload). If None, extracted via OCR.
        """
        img_path = Path(challenge_screenshot)

        # 1. Get challenge text
        if not challenge_prompt:
            challenge_prompt = await self._extract_challenge_text(img_path)
        logger.info(f"[CAPTCHA] Task: {challenge_prompt!r}")

        # 2. Split into 9 cells
        cells = self._split_cells(img_path)

        # 3. Classify each cell and collect results for report
        banner_path = self._tmp_dir / "banner.png"
        coordinates = []
        report_rows = []
        for row, col, cell_path in cells:
            answer = await self._classify_cell(cell_path, challenge_prompt, banner_path=banner_path)
            mark = "[YES] true" if answer else "[NO]  false"
            report_rows.append((row, col, cell_path, mark))
            if answer:
                coordinates.append(BoundingBoxCoordinate(box_2d=[row, col]))

        # 4. Print debug table
        logger.info(f"\n{'='*55}")
        logger.info(f"  CAPTCHA REPORT: \"{challenge_prompt}\"")
        logger.info(f"{'='*55}")
        logger.info(f"  {'Cell':<8} {'File':<20} {'Answer'}")
        logger.info(f"  {'-'*50}")
        for row, col, cell_path, mark in report_rows:
            logger.info(f"  [{row},{col}]    {cell_path.name:<20} {mark}")
        positive = [f"[{r},{c}]" for r, c, _, m in report_rows if "true" in m]
        logger.info(f"  {'-'*50}")
        logger.info(f"  Positive: {positive if positive else 'none (fallback [0,0])'}")
        logger.info(f"{'='*55}\n")

        # 5. Save examples to captcha_examples/<timestamp>/
        try:
            task_slug = "".join(c if c.isalnum() or c in " _-" else "" for c in challenge_prompt)[:40].strip().replace(" ", "_")
            save_dir = self.EXAMPLES_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_slug}"
            save_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(img_path, save_dir / "full.png")
            banner_path = self._tmp_dir / "banner.png"
            if banner_path.exists():
                shutil.copy(banner_path, save_dir / "banner.png")
            for row, col, cell_path, mark in report_rows:
                shutil.copy(cell_path, save_dir / f"cell_{row}_{col}.png")
            report_lines = [f"Task: {challenge_prompt}", ""]
            for row, col, cell_path, mark in report_rows:
                report_lines.append(f"[{row},{col}] {mark}")
            report_lines.append("")
            report_lines.append(f"Positive: {positive if positive else 'none (fallback [0,0])'}")
            (save_dir / "report.txt").write_text("\n".join(report_lines), encoding="utf-8")
            logger.info(f"[CAPTCHA] Example saved to: {save_dir}")
        except Exception as e:
            logger.warning(f"Failed to save captcha example: {e}")

        # Fallback: if nothing selected, pick first cell
        if not coordinates:
            coordinates = [BoundingBoxCoordinate(box_2d=[0, 0])]

        return ImageBinaryChallenge(
            challenge_prompt=challenge_prompt,
            coordinates=coordinates,
        )
