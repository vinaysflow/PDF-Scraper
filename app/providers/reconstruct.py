"""Reconstruct a visual HTML page from an ExtractionResult JSON.

Given the structured extraction output (text with bboxes, images with
positions, page dimensions), this module generates a self-contained HTML
document that visually approximates the original PDF layout.

Usage::

    from app.providers.reconstruct import reconstruct_html

    html_str = reconstruct_html(extraction_result_dict)
"""

from __future__ import annotations

import html as html_mod
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _css_color(srgb_int: int | None) -> str:
    """Convert PyMuPDF sRGB integer to CSS hex colour.  Default black."""
    if srgb_int is None or srgb_int == 0:
        return "#000"
    r = (srgb_int >> 16) & 0xFF
    g = (srgb_int >> 8) & 0xFF
    b = srgb_int & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def _scale(val: float | None, factor: float) -> float:
    """Scale a point value to pixels."""
    return round((val or 0) * factor, 1)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def reconstruct_html(
    result: dict[str, Any],
    scale_factor: float = 1.5,
    max_width_px: int = 920,
) -> str:
    """Build a self-contained HTML string from an extraction result dict.

    Parameters
    ----------
    result:
        A dict produced by ``ExtractionResult.model_dump()``.
    scale_factor:
        Multiplier from PDF points to CSS pixels (1pt ≈ 1.333px at 96dpi;
        1.5 gives a comfortable reading size).
    max_width_px:
        Maximum viewport width for the page container.

    Returns
    -------
    A complete HTML document string.
    """
    pages = result.get("pages", [])
    filename = result.get("filename", "Untitled")
    doc_id = result.get("doc_id", "")

    page_sections: list[str] = []

    for page in pages:
        page_num = page.get("page_number", 0)
        pw = page.get("page_width")
        ph = page.get("page_height")

        if pw and ph:
            container_w = min(_scale(pw, scale_factor), max_width_px)
            actual_scale = container_w / pw
            container_h = round(ph * actual_scale, 1)
        else:
            container_w = max_width_px
            container_h = 1100
            actual_scale = scale_factor

        # --- Layout blocks (positioned text spans) ---
        block_divs: list[str] = []
        layout_blocks = page.get("layout_blocks", [])

        for blk in layout_blocks:
            blk_type = blk.get("type", "text")
            bbox = blk.get("bbox")
            if not bbox:
                continue

            left = _scale(bbox.get("x"), actual_scale)
            top = _scale(bbox.get("y"), actual_scale)
            width = _scale(bbox.get("w"), actual_scale)
            height = _scale(bbox.get("h"), actual_scale)

            if blk_type == "text":
                text = html_mod.escape(blk.get("text", ""))
                font = blk.get("font", "sans-serif")
                size = round((blk.get("size") or 10) * actual_scale, 1)
                color = _css_color(blk.get("color"))
                block_divs.append(
                    f'<div class="blk txt" style="'
                    f"left:{left}px;top:{top}px;width:{width}px;height:{height}px;"
                    f"font-size:{size}px;font-family:'{font}',sans-serif;color:{color}"
                    f'">{text}</div>'
                )
            elif blk_type == "image":
                block_divs.append(
                    f'<div class="blk img-placeholder" style="'
                    f"left:{left}px;top:{top}px;width:{width}px;height:{height}px"
                    f'"><span>[image]</span></div>'
                )

        # --- Embedded images (base64) ---
        images = page.get("images", [])
        for img in images:
            bbox = img.get("bbox")
            b64 = img.get("base64_data")
            fmt = img.get("format", "png")
            if b64 and bbox:
                left = _scale(bbox.get("x"), actual_scale)
                top = _scale(bbox.get("y"), actual_scale)
                width = _scale(bbox.get("w"), actual_scale)
                height = _scale(bbox.get("h"), actual_scale)
                block_divs.append(
                    f'<img class="blk embedded-img" src="data:image/{fmt};base64,{b64}" '
                    f'style="left:{left}px;top:{top}px;width:{width}px;height:{height}px" '
                    f'alt="Embedded image page {page_num}" />'
                )

        # --- Fallback: if no layout blocks, render raw text ---
        if not block_divs and page.get("text"):
            raw_text = html_mod.escape(page["text"])
            block_divs.append(
                f'<pre class="fallback-text">{raw_text}</pre>'
            )

        blocks_html = "\n        ".join(block_divs)
        page_sections.append(f"""
    <div class="page-wrapper">
      <div class="page-header">Page {page_num}</div>
      <div class="page-canvas" style="width:{container_w}px;height:{container_h}px">
        {blocks_html}
      </div>
    </div>""")

    all_pages = "\n".join(page_sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Reconstruction: {html_mod.escape(filename)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f0f0f0;
    padding: 20px;
    color: #333;
  }}
  h1 {{
    text-align: center;
    margin-bottom: 8px;
    font-size: 1.4rem;
  }}
  .meta {{
    text-align: center;
    font-size: 0.85rem;
    color: #666;
    margin-bottom: 24px;
  }}
  .page-wrapper {{
    margin: 0 auto 32px auto;
    max-width: {max_width_px + 40}px;
  }}
  .page-header {{
    font-weight: 600;
    font-size: 0.9rem;
    color: #555;
    margin-bottom: 6px;
    padding-left: 4px;
  }}
  .page-canvas {{
    position: relative;
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0,0,0,.08);
    overflow: hidden;
  }}
  .blk {{
    position: absolute;
    white-space: pre;
    line-height: 1.15;
    overflow: hidden;
  }}
  .txt {{
    pointer-events: none;
  }}
  .img-placeholder {{
    background: #e8e8e8;
    border: 1px dashed #aaa;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
    font-size: 12px;
  }}
  .embedded-img {{
    object-fit: contain;
  }}
  .fallback-text {{
    padding: 16px;
    font-size: 13px;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.5;
    color: #444;
  }}
  /* Navigation */
  .nav {{
    position: fixed;
    top: 12px;
    right: 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    z-index: 100;
  }}
  .nav a {{
    display: block;
    padding: 4px 10px;
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 4px;
    text-decoration: none;
    color: #333;
    font-size: 0.8rem;
    text-align: center;
  }}
  .nav a:hover {{ background: #eef; }}
</style>
</head>
<body>
<h1>PDF Reconstruction</h1>
<p class="meta">{html_mod.escape(filename)} &middot; {len(pages)} pages &middot; doc_id: {html_mod.escape(doc_id[:12])}</p>
{all_pages}
</body>
</html>"""
