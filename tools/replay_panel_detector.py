"""Offline, local-only quest-panel replay; never writes images or OCR text.

Manifest entries have image, group, split, label (quest/absent), source,
rights, and optional panel/body [x,y,width,height] annotations. Keep every
frame and transformation from one source in the same group and split.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

from lvc.vision.binding import PixelRect
from lvc.vision.structural_panel import (
    QuestPanelDetector,
    StructuralPanelDetector,
    body_retains_reference,
    edge_checked_body,
    readable_body,
)
from lvc.vision.text_gate import OcrPass


def _rect(value: object) -> PixelRect | None:
    if value is None:
        return None
    if (not isinstance(value, list) or len(value) != 4
            or any(type(number) is not int for number in value)):
        raise ValueError("REPLAY_RECT_INVALID")
    return PixelRect(*value)


def _intersection(first: PixelRect, second: PixelRect) -> int:
    return (max(0, min(first.x + first.width, second.x + second.width)
                - max(first.x, second.x))
            * max(0, min(first.y + first.height, second.y + second.height)
                  - max(first.y, second.y)))


def _tokens(passage: OcrPass) -> Counter[str]:
    return Counter(value for word in passage.words
                   if (value := "".join(character for character in word.text.casefold()
                                        if character.isalnum())))


def replay(manifest: Path, detector: QuestPanelDetector,
           layout_ocr: Callable[[Image.Image], OcrPass] | None = None,
           *, edge_refine: bool = False) -> dict[str, Any]:
    """Return numeric localization and crop coverage, not image contents."""
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("REPLAY_MANIFEST_INVALID")
    group_splits: dict[str, str] = {}
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or not {"image", "group", "split", "label",
                                               "source", "rights"} <= item.keys():
            raise ValueError("REPLAY_ITEM_INVALID")
        group, split, label = item["group"], item["split"], item["label"]
        if (not isinstance(group, str) or not group
                or split not in {"development", "holdout"}
                or label not in {"quest", "absent"}
                or not isinstance(item["source"], str)
                or not isinstance(item["rights"], str)
                or not isinstance(item["image"], str)):
            raise ValueError("REPLAY_ITEM_INVALID")
        if group in group_splits and group_splits[group] != split:
            raise ValueError("REPLAY_GROUP_SPLIT_LEAK")
        group_splits[group] = split
        path = (manifest.parent / item["image"]).resolve()
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("REPLAY_IMAGE_INVALID")
        with Image.open(path) as opened:
            opened.load()
            frame = opened.convert("RGB")
        expected_panel = _rect(item.get("panel"))
        expected_body = _rect(item.get("body"))
        if label == "quest" and ((expected_panel is None) != (expected_body is None)):
            raise ValueError("REPLAY_LABEL_INCOMPLETE")
        if label == "absent" and (expected_panel is not None or expected_body is not None):
            raise ValueError("REPLAY_LABEL_INVALID")
        for rect in (expected_panel, expected_body):
            if rect is not None and not rect.inside(*frame.size):
                raise ValueError("REPLAY_LABEL_OUTSIDE_FRAME")
        detection = detector.detect(frame)
        selected = detection.selected
        key = f"{split}_{label}_{detection.reason.lower()}"
        counts[key] += 1
        row: dict[str, Any] = {"group": group, "split": split,
                               "label": label, "reason": detection.reason,
                               "candidate_count": len(detection.candidates)}
        broad_body = selected.body if selected is not None else None
        if selected is not None and edge_refine:
            refined = edge_checked_body(frame, selected)
            row["refined_body_found"] = refined is not None
            if refined is None:
                counts[f"{split}_{label}_edge_abstain"] += 1
                selected = None
            else:
                selected = replace(selected, body=refined)
        candidate_passage = None
        if selected is not None and layout_ocr is not None:
            candidate_passage = layout_ocr(frame.crop((selected.body.x, selected.body.y,
                                                       selected.body.x + selected.body.width,
                                                       selected.body.y + selected.body.height)))
            row["readable_body"] = readable_body(candidate_passage)
            row["ocr_candidate_lines"] = len(candidate_passage.raw_text.splitlines())
            row["ocr_candidate_clipped_words"] = sum(word.clipped
                                                        for word in candidate_passage.words)
            if edge_refine and broad_body is not None:
                reference_passage = layout_ocr(frame.crop((
                    broad_body.x, broad_body.y, broad_body.x + broad_body.width,
                    broad_body.y + broad_body.height)))
                row["broad_words_retained"] = body_retains_reference(
                    reference_passage, candidate_passage)
        if selected is not None and expected_body is not None:
            common = _intersection(selected.body, expected_body)
            # Coverage detects missing dialogue; purity detects objectives,
            # footer controls, or other content included by the crop.
            row["body_coverage"] = round(
                common / (expected_body.width * expected_body.height), 4)
            row["body_purity"] = round(
                common / (selected.body.width * selected.body.height), 4)
            if expected_panel is not None:
                common_panel = _intersection(selected.panel, expected_panel)
                union = (selected.panel.width * selected.panel.height
                         + expected_panel.width * expected_panel.height - common_panel)
                row["panel_iou"] = round(common_panel / union, 4)
            if layout_ocr is not None and candidate_passage is not None:
                target = layout_ocr(frame.crop((expected_body.x, expected_body.y,
                                                expected_body.x + expected_body.width,
                                                expected_body.y + expected_body.height)))
                target_words, candidate_words = (_tokens(target),
                                                 _tokens(candidate_passage))
                agreed = sum((target_words & candidate_words).values())
                row["ocr_word_recall"] = round(
                    agreed / sum(target_words.values()), 4) if target_words else None
                row["ocr_word_precision"] = round(
                    agreed / sum(candidate_words.values()), 4) if candidate_words else None
        results.append(row)
    return {"count": len(results), "groups": len(group_splits),
            "counts": dict(sorted(counts.items())), "results": results,
            "edge_refine": edge_refine,
            "contains_pixels_or_text": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--ocr-layout", action="store_true",
                        help="locally compare OCR words in annotated and proposed body crops")
    parser.add_argument("--edge-refine", action="store_true",
                        help="evaluate the per-frame clear-edge body crop and retention gate")
    args = parser.parse_args()
    layout_ocr: Callable[[Image.Image], OcrPass] | None = None
    if args.ocr_layout:
        from lvc.platform.windows.lotro_user_probe import recognize

        def _layout_ocr(image: Image.Image) -> OcrPass:
            return recognize(image, alternative=False)

        layout_ocr = _layout_ocr
    print(json.dumps(replay(args.manifest, StructuralPanelDetector(), layout_ocr,
                            edge_refine=args.edge_refine),
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
