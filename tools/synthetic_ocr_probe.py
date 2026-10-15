"""Exercise installed Tesseract on an original in-memory text fixture only."""
# pyright: reportMissingImports=false
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytesseract
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pytesseract import Output

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lvc.vision.text_gate import OcrPass, OcrWord, decide_text

TEXT = "Bring 10 stones, not 18."
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
FONT = Path(r"C:\Windows\Fonts\arial.ttf")


def recognize(image: Image.Image) -> OcrPass:
    data = pytesseract.image_to_data(image, lang="eng", config="--psm 7",
                                     output_type=Output.DICT)
    words = tuple(OcrWord(word.strip(), float(score))
                  for word, score in zip(data["text"], data["conf"], strict=True)
                  if word.strip() and float(score) >= 0)
    return OcrPass(" ".join(word.text for word in words), words)


def main() -> int:
    if not TESSERACT.is_file() or not FONT.is_file():
        raise RuntimeError("Expected local Tesseract or Windows font is unavailable")
    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT)
    if "eng" not in pytesseract.get_languages(config=""):
        raise RuntimeError("Installed Tesseract English data is unavailable")
    image = Image.new("RGB", (850, 110), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 22), TEXT, fill="black", font=ImageFont.truetype(str(FONT), 44))
    first = recognize(image)
    alternative = recognize(ImageOps.grayscale(image).resize((1700, 220)))
    decision = decide_text(first, alternative, qualified_region=True)
    passed = (decision.accepted_text == TEXT and first.raw_text == TEXT
              and alternative.raw_text == TEXT)
    report = {
        "scope": "ORIGINAL_IN_MEMORY_SYNTHETIC_OCR_ONLY",
        "status": "PASSED" if passed else "FAILED",
        "tesseract_version": str(pytesseract.get_tesseract_version()),
        "language": "eng",
        "config": "--psm 7",
        "normal_text": first.raw_text,
        "alternative_text": alternative.raw_text,
        "normal_confidence": [word.confidence for word in first.words],
        "alternative_confidence": [word.confidence for word in alternative.words],
        "gate_reason": decision.reason,
        "screen_or_game_capture": False,
        "image_saved": False,
        "production_ocr_qualified": False,
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
