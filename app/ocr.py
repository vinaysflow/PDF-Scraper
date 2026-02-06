"""Tesseract-based OCR extraction."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytesseract
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image, ImageFilter, ImageOps

from .utils import PdfProcessingError, similarity_ratio

OCR_OEM = 1
OCR_PSM_CANDIDATES = (4, 6, 3, 11)
OCR_LANG = "eng"
OCR_THRESHOLD = 200
OCR_SELECTION_MIN_CONF = 70.0
OCR_USE_OTSU = True
OCR_USE_OSD = True
OCR_RETRY_DPI = (800, 1000)
OCR_RETRY_THRESHOLDS = (220, 180)
OCR_RETRY_OSD = (True, False)
OCR_PREPROCESS_STRATEGIES = (
    {
        "name": "standard",
        "threshold": OCR_THRESHOLD,
        "use_osd": OCR_USE_OSD,
        "median_size": 3,
        "unsharp": (1, 150, 3),
        "autocontrast_cutoff": 1,
    },
    {
        "name": "aggressive",
        "threshold": 220,
        "use_osd": OCR_USE_OSD,
        "median_size": 5,
        "unsharp": (2, 200, 3),
        "autocontrast_cutoff": 2,
    },
)


LAYOUT_PRESETS = {
    "text": {
        "psm": (6, 3),
        "preprocess": ("standard",),
    },
    "table": {
        "psm": (4, 11, 6),
        "preprocess": ("aggressive", "standard"),
    },
    "noisy": {
        "psm": (4, 6, 11, 3),
        "preprocess": ("aggressive", "standard"),
    },
}


def _build_config(psm: int, lang: str = OCR_LANG, tessdata_path: str | None = None) -> str:
    parts = [f"--oem {OCR_OEM}", f"--psm {psm}", f"-l {lang}"]
    if tessdata_path:
        parts.append(f"--tessdata-dir \"{tessdata_path}\"")
    return " ".join(parts)


def _otsu_threshold(gray: Image.Image) -> int:
    """Compute an Otsu threshold for a grayscale image."""

    histogram = gray.histogram()
    total = sum(histogram)
    if total == 0:
        return OCR_THRESHOLD
    sum_total = 0
    for index, count in enumerate(histogram):
        sum_total += index * count

    sum_background = 0
    weight_background = 0
    max_variance = 0.0
    threshold = OCR_THRESHOLD

    for index, count in enumerate(histogram):
        weight_background += count
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += index * count
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        variance_between = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )
        if variance_between > max_variance:
            max_variance = variance_between
            threshold = index

    return threshold


def _apply_osd_rotation(
    image: Image.Image, use_osd: bool, tessdata_path: str | None
) -> Image.Image:
    """Rotate using Tesseract OSD orientation when available."""

    if not use_osd:
        return image
    try:
        config = "--psm 0"
        if tessdata_path:
            config = f'{config} --tessdata-dir "{tessdata_path}"'
        osd = pytesseract.image_to_osd(
            image, output_type=pytesseract.Output.STRING, config=config
        )
        for line in osd.splitlines():
            if line.strip().startswith("Rotate:"):
                rotate = int(line.split(":")[1].strip())
                if rotate:
                    return image.rotate(-rotate, expand=True)
    except Exception:
        return image
    return image


def _select_threshold(gray: Image.Image, threshold: int) -> int:
    if OCR_USE_OTSU:
        otsu = _otsu_threshold(gray)
        return int((otsu + threshold) / 2)
    return threshold


def preprocess_image(
    image: Image.Image,
    threshold: int = OCR_THRESHOLD,
    use_osd: bool = OCR_USE_OSD,
    median_size: int = 3,
    unsharp: tuple[int, int, int] = (1, 150, 3),
    autocontrast_cutoff: int = 1,
    tessdata_path: str | None = None,
) -> Image.Image:
    """Apply Pillow preprocessing to improve OCR quality."""

    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=autocontrast_cutoff)
    gray = gray.filter(ImageFilter.MedianFilter(size=median_size))
    gray = gray.filter(
        ImageFilter.UnsharpMask(
            radius=unsharp[0], percent=unsharp[1], threshold=unsharp[2]
        )
    )
    gray = _apply_osd_rotation(gray, use_osd, tessdata_path)
    threshold = _select_threshold(gray, threshold)
    bw = gray.point(lambda x: 255 if x > threshold else 0, mode="1")
    return bw


def _extract_tokens(ocr_data: dict) -> tuple[list[dict], list[str], list[float]]:
    tokens: list[dict] = []
    token_texts: list[str] = []
    confidences: list[float] = []
    text_items = ocr_data.get("text", [])
    for index in range(len(text_items)):
        text = (text_items[index] or "").strip()
        if not text:
            continue
        try:
            confidence = float(ocr_data["conf"][index])
        except Exception:
            confidence = -1.0
        if confidence < 0:
            continue
        token_texts.append(text)
        confidences.append(confidence)
        tokens.append(
            {
                "text": text,
                "bbox": {
                    "x": int(ocr_data["left"][index]),
                    "y": int(ocr_data["top"][index]),
                    "w": int(ocr_data["width"][index]),
                    "h": int(ocr_data["height"][index]),
                },
                "confidence": confidence,
            }
        )
    return tokens, token_texts, confidences


def _score_page(confidences: list[float]) -> tuple[float, int]:
    if not confidences:
        return 0.0, 0
    filtered = [c for c in confidences if c >= OCR_SELECTION_MIN_CONF]
    if not filtered:
        return 0.0, len(confidences)
    return sum(filtered) / len(filtered), len(confidences)


def _page_text(token_texts: list[str]) -> str:
    return " ".join(token_texts).strip()


def classify_layout(image: Image.Image) -> str:
    """Classify page layout as text/table/noisy using line density."""

    gray = _to_cv_gray(image)
    horizontal, vertical = detect_table_lines(gray)
    line_density = (cv2.countNonZero(horizontal) + cv2.countNonZero(vertical)) / (
        gray.shape[0] * gray.shape[1]
    )

    small = image.convert("L").resize((400, 400))
    edges = small.filter(ImageFilter.FIND_EDGES)
    edge_pixels = sum(1 for p in edges.getdata() if p > 40)
    total_pixels = 400 * 400
    edge_density = edge_pixels / total_pixels
    ink_pixels = sum(1 for p in small.getdata() if p < 200)
    ink_density = ink_pixels / total_pixels

    if line_density > 0.01:
        return "table"
    if ink_density > 0.10 and edge_density < 0.08:
        return "text"
    return "noisy"


def _to_cv_gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)


def detect_table_lines(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Detect horizontal and vertical lines for table pages."""

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horizontal = binary.copy()
    vertical = binary.copy()

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))

    horizontal = cv2.erode(horizontal, h_kernel, iterations=1)
    horizontal = cv2.dilate(horizontal, h_kernel, iterations=2)

    vertical = cv2.erode(vertical, v_kernel, iterations=1)
    vertical = cv2.dilate(vertical, v_kernel, iterations=2)

    return horizontal, vertical


def remove_table_lines(gray: np.ndarray, horizontal: np.ndarray, vertical: np.ndarray) -> np.ndarray:
    """Remove detected gridlines from grayscale image."""

    grid = cv2.bitwise_or(horizontal, vertical)
    cleaned = cv2.inpaint(gray, grid, 3, cv2.INPAINT_TELEA)
    return cleaned


def extract_table_cells(horizontal: np.ndarray, vertical: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Extract bounding boxes for table cells using line intersections."""

    grid = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 20 or h < 20:
            continue
        boxes.append((x, y, w, h))
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    return boxes


def ocr_table_cells(
    gray: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    ocr_lang: str,
    tessdata_path: str | None,
) -> tuple[str, list[dict]]:
    """OCR each table cell and return combined text + tokens."""

    tokens: list[dict] = []
    rows: list[list[str]] = []
    current_row_y = None
    current_row: list[str] = []

    for x, y, w, h in boxes:
        if current_row_y is None or abs(y - current_row_y) > h:
            if current_row:
                rows.append(current_row)
            current_row = []
            current_row_y = y
        cell = gray[y : y + h, x : x + w]
        cell_img = Image.fromarray(cell)
        config = _build_config(7, lang=ocr_lang, tessdata_path=tessdata_path)
        text = pytesseract.image_to_string(cell_img, config=config).strip()
        if text:
            current_row.append(text)
            tokens.append(
                {
                    "text": text,
                    "bbox": {"x": x, "y": y, "w": w, "h": h},
                    "confidence": 0.0,
                }
            )
    if current_row:
        rows.append(current_row)

    table_text = "\n".join(["\t".join(row) for row in rows]).strip()
    return table_text, tokens


def _ocr_page(
    image: Image.Image,
    psm_candidates: tuple[int, ...],
    preprocess_strategies: tuple[dict, ...],
    ocr_lang: str,
    tessdata_path: str | None,
) -> dict:
    candidates: list[dict] = []
    for preprocess in preprocess_strategies:
        processed_image = preprocess_image(
            image,
            threshold=preprocess["threshold"],
            use_osd=preprocess["use_osd"],
            median_size=preprocess["median_size"],
            unsharp=preprocess["unsharp"],
            autocontrast_cutoff=preprocess["autocontrast_cutoff"],
            tessdata_path=tessdata_path,
        )
        for psm in psm_candidates:
            config = _build_config(psm, lang=ocr_lang, tessdata_path=tessdata_path)
            ocr_data = pytesseract.image_to_data(
                processed_image,
                output_type=pytesseract.Output.DICT,
                config=config,
            )
            tokens, token_texts, confidences = _extract_tokens(ocr_data)
            score = _score_page(confidences)
            candidates.append(
                {
                    "text": _page_text(token_texts),
                    "tokens": tokens,
                    "score": (score[0], score[1]),
                    "strategy": {
                        "name": preprocess["name"],
                        "psm": psm,
                        "threshold": preprocess["threshold"],
                        "use_osd": preprocess["use_osd"],
                        "median_size": preprocess["median_size"],
                        "unsharp": preprocess["unsharp"],
                        "autocontrast_cutoff": preprocess["autocontrast_cutoff"],
                    },
                }
            )

    if not candidates:
        return {
            "text": "",
            "tokens": [],
            "pass_similarity": None,
            "strategy": {
                "name": "none",
                "psm_candidates": list(psm_candidates),
            },
        }

    for candidate in candidates:
        similarities: list[float] = []
        for other in candidates:
            if other is candidate:
                continue
            ratio = similarity_ratio(candidate["text"], other["text"])
            if ratio is not None:
                similarities.append(ratio)
        candidate["consensus_similarity"] = (
            sum(similarities) / len(similarities) if similarities else 1.0
        )

    best_candidate = max(
        candidates,
        key=lambda item: (item["consensus_similarity"], item["score"]),
    )
    return {
        "text": best_candidate["text"],
        "tokens": best_candidate["tokens"],
        "pass_similarity": best_candidate["consensus_similarity"],
        "strategy": {
            **best_candidate["strategy"],
            "psm_candidates": list(psm_candidates),
            "consensus_candidates": len(candidates),
        },
    }



def _default_ocr_workers() -> int:
    """Default number of parallel OCR workers (env OCR_WORKERS, or 4)."""
    try:
        return max(1, min(32, int(os.environ.get("OCR_WORKERS", "4"))))
    except (TypeError, ValueError):
        return 4


def extract_with_ocr(
    pdf_path: Path,
    dpi: int = 300,
    max_pages: int | None = None,
    ocr_lang: str = OCR_LANG,
    tessdata_path: str | None = None,
    images: list | None = None,
    workers: int | None = None,
) -> tuple[str, list[dict]]:
    """Render PDF pages (or use provided images) and run Tesseract OCR in parallel."""

    if images is None:
        try:
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=1,
                last_page=max_pages,
            )
        except Exception as exc:  # pragma: no cover - depends on system binaries
            raise PdfProcessingError(f"OCR rendering failed: {exc}") from exc

    n_pages = len(images)
    if n_pages == 0:
        return "", []

    n_workers = workers if workers is not None else _default_ocr_workers()
    n_workers = min(n_workers, n_pages)

    if n_workers <= 1:
        pages = [
            _process_one_ocr_page(i, img, ocr_lang, tessdata_path)
            for i, img in enumerate(images, start=1)
        ]
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            pages = list(
                executor.map(
                    lambda item: _process_one_ocr_page(
                        item[0], item[1], ocr_lang, tessdata_path
                    ),
                    [(i, img) for i, img in enumerate(images, start=1)],
                )
            )

    full_text_parts = [p["text"] for p in pages if p.get("text")]
    return "\n".join(full_text_parts).strip(), pages


def _process_one_ocr_page(
    page_number: int,
    image: Image.Image,
    ocr_lang: str,
    tessdata_path: str | None,
) -> dict:
    """Process a single page: classify layout, run table or full OCR, return page dict. Used for parallel OCR."""
    layout = classify_layout(image)
    preset = LAYOUT_PRESETS.get(layout, LAYOUT_PRESETS["noisy"])
    selected_preprocess = tuple(
        strat
        for strat in OCR_PREPROCESS_STRATEGIES
        if strat["name"] in preset["preprocess"]
    )
    if not selected_preprocess:
        selected_preprocess = OCR_PREPROCESS_STRATEGIES
    page_text = ""
    page_tokens: list = []
    pass_similarity = None
    strategy: dict = {}

    if layout == "table":
        gray = _to_cv_gray(image)
        horizontal, vertical = detect_table_lines(gray)
        cleaned = remove_table_lines(gray, horizontal, vertical)
        boxes = extract_table_cells(horizontal, vertical)
        if boxes:
            page_text, page_tokens = ocr_table_cells(
                cleaned, boxes, ocr_lang=ocr_lang, tessdata_path=tessdata_path
            )
        else:
            result = _ocr_page(
                image=image,
                psm_candidates=preset["psm"],
                preprocess_strategies=selected_preprocess,
                ocr_lang=ocr_lang,
                tessdata_path=tessdata_path,
            )
            page_text = result["text"]
            page_tokens = result["tokens"]
            pass_similarity = result["pass_similarity"]
            strategy = result["strategy"]
        strategy = {**strategy, "table_cells": len(boxes)}
    else:
        result = _ocr_page(
            image=image,
            psm_candidates=preset["psm"],
            preprocess_strategies=selected_preprocess,
            ocr_lang=ocr_lang,
            tessdata_path=tessdata_path,
        )
        page_text = result["text"]
        page_tokens = result["tokens"]
        pass_similarity = result["pass_similarity"]
        strategy = result["strategy"]

    return {
        "page_number": page_number,
        "text": page_text,
        "tokens": page_tokens,
        "pass_similarity": pass_similarity,
        "strategy": strategy,
        "layout": layout,
    }


def rerun_page_ocr(
    pdf_path: Path,
    page_number: int,
    attempt: int,
    ocr_lang: str = OCR_LANG,
    tessdata_path: str | None = None,
) -> dict:
    """Re-run OCR for a single page using a retry strategy."""

    threshold = OCR_RETRY_THRESHOLDS[attempt % len(OCR_RETRY_THRESHOLDS)]
    use_osd = OCR_RETRY_OSD[attempt % len(OCR_RETRY_OSD)]
    psm_candidates = (
        tuple(reversed(OCR_PSM_CANDIDATES)) if attempt == 0 else OCR_PSM_CANDIDATES
    )
    dpi = OCR_RETRY_DPI[attempt % len(OCR_RETRY_DPI)]
    preprocess_strategies = (
        {
            "name": f"retry-{attempt + 1}",
            "threshold": threshold,
            "use_osd": use_osd,
            "median_size": 5,
            "unsharp": (2, 200, 3),
            "autocontrast_cutoff": 2,
        },
    )

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
    )
    if not images:
        raise PdfProcessingError(f"OCR retry failed to render page {page_number}.")
    layout = classify_layout(images[0])
    preset = LAYOUT_PRESETS.get(layout, LAYOUT_PRESETS["noisy"])
    result = _ocr_page(
        image=images[0],
        psm_candidates=preset["psm"] if preset else psm_candidates,
        preprocess_strategies=preprocess_strategies,
        ocr_lang=ocr_lang,
        tessdata_path=tessdata_path,
    )
    result["strategy"] |= {"dpi": dpi, "attempt": attempt + 1}
    result["layout"] = layout
    return result
