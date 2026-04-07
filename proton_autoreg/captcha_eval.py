"""
Оценка качества contour matcher.
Показывает визуализации _match.png, ты жмёшь Y/N.

Управление:
  Y — правильно (best match верный)
  N — неправильно
  S — пропустить (не уверен)
  Q — выйти и показать метрики

python captcha_eval.py
"""
import json
from pathlib import Path

import cv2

DATASET_DIR = Path(__file__).parent / "captcha_dataset"
LABELS_FILE = DATASET_DIR / "labels.jsonl"
EVAL_FILE = DATASET_DIR / "eval_results.jsonl"


def main():
    # Загрузить labels
    labels = []
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))

    # Уже оценённые
    evaluated = set()
    if EVAL_FILE.exists():
        with open(EVAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    evaluated.add(d["screenshot"])

    # Найти _match.png файлы
    match_files = []
    for label in labels:
        screenshot = label["screenshot"]
        if screenshot in evaluated:
            continue
        match_path = DATASET_DIR / screenshot.replace(".png", "_match.png")
        if match_path.exists():
            match_files.append((screenshot, match_path, label))

    if not match_files:
        print("Нет файлов для оценки (все уже оценены или нет _match.png)")
        return

    print(f"Файлов для оценки: {len(match_files)}")
    print("Y=правильно | N=неправильно | S=пропустить | Q=выйти\n")

    cv2.namedWindow("Eval", cv2.WINDOW_NORMAL)

    correct = 0
    wrong = 0
    skipped = 0

    for i, (screenshot, match_path, label) in enumerate(match_files):
        img = cv2.imread(str(match_path))
        if img is None:
            continue

        prompt = label.get("prompt", "?")
        print(f"[{i+1}/{len(match_files)}] {screenshot}")
        print(f"  Prompt: {prompt}")

        cv2.imshow("Eval", img)

        while True:
            key = cv2.waitKey(0) & 0xFF

            if key == ord("y") or key == ord("Y"):
                result = {"screenshot": screenshot, "verdict": "correct", "prompt": prompt}
                correct += 1
                print(f"  -> CORRECT")
                break
            elif key == ord("n") or key == ord("N"):
                result = {"screenshot": screenshot, "verdict": "wrong", "prompt": prompt}
                wrong += 1
                # Копировать в отдельную папку для анализа ошибок
                wrong_dir = DATASET_DIR / "eval_wrong"
                wrong_dir.mkdir(exist_ok=True)
                cv2.imwrite(str(wrong_dir / screenshot.replace(".png", "_match.png")), img)
                print(f"  -> WRONG (saved to eval_wrong/)")
                break
            elif key == ord("s") or key == ord("S"):
                result = {"screenshot": screenshot, "verdict": "skip"}
                skipped += 1
                print(f"  -> SKIP")
                break
            elif key == ord("q") or key == ord("Q"):
                print("\nВыход")
                _print_stats(correct, wrong, skipped)
                cv2.destroyAllWindows()
                return

        with open(EVAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")

    cv2.destroyAllWindows()
    print()
    _print_stats(correct, wrong, skipped)


def _print_stats(correct: int, wrong: int, skipped: int):
    total = correct + wrong
    if total == 0:
        print("Нет оценок")
        return

    accuracy = correct / total * 100
    print(f"===== Метрики =====")
    print(f"  Correct:  {correct}")
    print(f"  Wrong:    {wrong}")
    print(f"  Skipped:  {skipped}")
    print(f"  Accuracy: {accuracy:.1f}% ({correct}/{total})")


if __name__ == "__main__":
    main()
