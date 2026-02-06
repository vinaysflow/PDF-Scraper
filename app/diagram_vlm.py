"""Pluggable VLM for diagram/figure description and structure extraction."""

from __future__ import annotations

import base64
import json
import os
import time
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

VLM_TIMEOUT_SEC = 30
VLM_MAX_RETRIES = 2
VLM_MODEL_DEFAULT = "gpt-4o-mini"


def _pil_to_base64_png(image: "Image.Image") -> str:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _is_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def describe_figure(
    image: "Image.Image",
    prompt_type: str = "describe",
    model: str = VLM_MODEL_DEFAULT,
    timeout_sec: int = VLM_TIMEOUT_SEC,
    max_retries: int = VLM_MAX_RETRIES,
) -> str | None:
    """
    Describe or structure a diagram image using OpenAI Vision.
    prompt_type: "describe" -> short paragraph; "structure" -> JSON structure.
    Returns response text or None on error / not configured.
    """
    if not _is_configured():
        return None
    try:
        import openai
    except ImportError:
        return None

    b64 = _pil_to_base64_png(image)
    if prompt_type == "describe":
        prompt = (
            "Describe this diagram or figure in one short paragraph. "
            "If it is a flowchart or process diagram, list the main steps and how they connect."
        )
    elif prompt_type == "structure":
        prompt = (
            "Describe this diagram as structured data. "
            'Respond with JSON only, e.g. {"type": "flowchart|chart|photo|other", "elements": [], "connections": []}. '
            "If it is a chart, include axis labels and data series if visible."
        )
    else:
        prompt = "Describe this image in one short paragraph."

    client = openai.OpenAI()
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                timeout=timeout_sec,
            )
            if resp.choices and resp.choices[0].message.content:
                return resp.choices[0].message.content.strip()
            return None
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))
    return None


def extract_chart_data(
    image: "Image.Image",
    model: str = VLM_MODEL_DEFAULT,
    timeout_sec: int = VLM_TIMEOUT_SEC,
) -> dict | None:
    """
    Ask VLM to extract chart data (axis labels, values, series) as JSON.
    Returns dict or None.
    """
    if not _is_configured():
        return None
    text = describe_figure(
        image,
        prompt_type="structure",
        model=model,
        timeout_sec=timeout_sec,
        max_retries=1,
    )
    if not text:
        return None
    try:
        # Strip markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)
    except json.JSONDecodeError:
        return None
