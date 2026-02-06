# Plan: Layout-specific handling

## Current state

- **Layout detection** (`app/ocr.py`): `classify_layout()` → `"table"` | `"text"` | `"noisy"` using line density + ink/edge density.
- **OCR per layout** (`LAYOUT_PRESETS`): PSM candidates and preprocess strategy differ by layout; table pages can use cell-based OCR.
- **Quality per layout** (`app/extract.py` `_page_quality`): Only **table** and **noisy** get relaxed gates; **text** (and `None`) use default/strict gates. Layout overrides are **hardcoded** and **override** `quality_target` (e.g. 90) for table/noisy.

Observed failures (e.g. maths question paper 01):

- **dual_pass_similarity** &lt; 0.90 on pages classified as **text** (no relaxation).
- **tika_similarity** &lt; 0.90 on page 1 (Tika text present but very different from OCR) → strict gate fails even when we correctly choose Tika.
- **low_conf_ratio** + **dual_pass_similarity** on one hard page (e.g. diagram/table-like) → may be misclassified or need a dedicated “hard” layout.

---

## Goals

1. **Single source of truth** for layout-specific behaviour: OCR presets + quality gates in one place, consistent with `quality_target`.
2. **Respect quality_target** for table/noisy (no fixed overrides that ignore 90% target).
3. **Text layout** optionally gets slight relaxation for dual_pass when target is 90, or a dedicated “mixed” handling when Tika and OCR disagree.
4. **Tika-chosen pages**: when we select Tika and tika_similarity is low, optionally **skip or relax** the tika_similarity gate (we are not using OCR for that page).
5. **Retries**: keep layout-specific OCR on retries; optionally add layout-specific retry strategies (e.g. extra PSMs for text that failed dual_pass).

---

## Phase 1: Centralize layout–quality config (extract.py)

**1.1 Define layout–quality overrides next to constants**

- Add a structure keyed by layout (and optionally by quality_target), e.g.:

  - `LAYOUT_QUALITY_OVERRIDES: dict[str, dict]` with keys `"table"`, `"noisy"`, and optionally `"text"`.
  - Each value: `max_low_conf_ratio`, `min_pass_similarity`, `min_tika_similarity`, `min_avg_confidence` (only keys that override).
  - For table/noisy, use values that are **relaxed** but **consistent with quality_target** when present (e.g. for target 90: min_pass 0.85 for table instead of 0.75 if we want to align with 90%).

- Keep **base** gates from `quality_overrides` (from `QUALITY_TARGET_OVERRIDES[90]`) and **merge** layout overrides on top (layout can only relax, not tighten beyond target).

**1.2 Use merged gates in `_page_quality`**

- Compute base gates from `quality_overrides` (or defaults).
- If `layout` is in `LAYOUT_QUALITY_OVERRIDES`, merge: for each key present in layout overrides, use `min(base, layout)` for mins and `max(base, layout)` for maxes (so layout never tightens).
- Apply merged gates to the four checks (avg_confidence, low_conf_ratio, dual_pass_similarity, tika_similarity).

**Deliverable:** Layout-specific quality gates driven by config; table/noisy respect quality_target; optional “text” relaxation (e.g. min_dual_pass 0.88 when target 90).

---

## Phase 2: Tika-chosen pages and tika_similarity gate

**2.1 When source is Tika, optionally skip or relax tika_similarity**

- In `_page_quality`, after computing `decision` and `selected_source`:
  - If `selected_source == "tika"` and `tika_similarity is not None` and we have a config flag (e.g. `relax_tika_gate_when_tika_chosen` or part of layout/quality config):
    - **Option A:** Do not add `"tika_similarity"` to `failed_gates` when we chose Tika (page is “approved” for that gate when Tika is selected).
    - **Option B:** Use a lower threshold for tika_similarity when Tika is chosen (e.g. 0.5 or 0.0) so we don’t fail the page.

- Prefer **Option A** so that “we trust Tika for this page” does not fail the document.

**2.2 Config**

- Add a single flag (e.g. in quality_overrides or in a small constants block): `skip_tika_similarity_gate_when_tika_selected: bool = True` for quality_target 90.

**Deliverable:** Pages where we correctly choose Tika no longer fail solely on tika_similarity.

---

## Phase 3: Layout detection and “mixed” / “diagram” (optional)

**3.1 Optional: “mixed” layout when Tika vs OCR strongly disagree**

- After OCR and Tika text are available (in extract, when building quality), if `tika_text` and `ocr_text` are both non-empty and `similarity_ratio(tika_text, ocr_text) < 0.3`, set a **derived** layout or flag, e.g. `layout_effective = "mixed"` for quality only (do not change OCR).
- In `LAYOUT_QUALITY_OVERRIDES`, add `"mixed"`: e.g. `min_tika_similarity = 0.0` (and optionally relaxed dual_pass), so such pages are not failed on tika_similarity.

**3.2 Optional: “diagram” or “dense” layout**

- In `classify_layout`, if we already have high edge density + high ink but not table, we could return `"noisy"` (already handled). If we want a separate “diagram” class (e.g. very low dual_pass, high low_conf_ratio), we could add a **post-OCR** check: if `pass_similarity < 0.3` and `low_conf_ratio > 0.7`, treat as “diagram” for quality and apply strong relaxation (e.g. dual_pass 0.5, low_conf 0.9). This is optional and can be Phase 4.

**Deliverable (Phase 3):** Optional “mixed” handling so low Tika–OCR similarity doesn’t fail the page when we still choose Tika or relax the gate.

---

## Phase 4: OCR-side layout refinements (optional)

**4.1 Text layout: improve dual_pass_similarity**

- For layout `"text"`, add one more PSM candidate (e.g. 4 or 13) to `LAYOUT_PRESETS["text"]["psm"]` and/or add a second preprocess strategy so two passes are more likely to agree.
- Or: in `rerun_page_ocr`, for pages that failed only `dual_pass_similarity`, retry with a “text-optimized” preset (more PSMs, both standard and aggressive).

**4.2 Table layout: pass_similarity for cell OCR**

- Today table pages using cell OCR don’t get `pass_similarity` (no second pass). Optionally run a second full-page pass (e.g. PSM 6) and compute similarity between cell-OCR text and full-page text to populate `pass_similarity` for tables (so quality gates can apply).

**Deliverable:** Better dual_pass for text; optional pass_similarity for table cell OCR.

---

## Implementation order (recommended)

| Step | Task | Files |
|------|------|--------|
| 1 | Add `LAYOUT_QUALITY_OVERRIDES` and merge logic in `_page_quality`; make table/noisy respect quality_target | `app/extract.py` |
| 2 | Add “skip or relax tika_similarity when selected_source is tika” | `app/extract.py` |
| 3 | (Optional) Add “mixed” layout/flag and gate relaxation for low Tika–OCR similarity | `app/extract.py` |
| 4 | (Optional) Extend LAYOUT_PRESETS for text (PSM/preprocess) and/or table pass_similarity | `app/ocr.py` |

---

## Success criteria

- With **quality_target 90** and layout-specific handling:
  - Pages that **choose Tika** do not fail on **tika_similarity** alone.
  - **Table** and **noisy** pages use gates that are relaxed but aligned with the 90% target (configurable).
  - **Text** pages can get a small dual_pass relaxation (e.g. 0.88) when target is 90 so borderline pages (e.g. 0.88–0.90) can be approved.
- **Rerun test**: Re-run `english maths question paper 01.pdf` with `--quality-target 90` and expect more pages **approved** (e.g. page 1 and possibly 2, 3, 6) without lowering standards on clearly good pages.

---

## Config sketch (for Phase 1)

```python
# Layout overrides: only specify keys that relax relative to base (quality_target).
# Base for target 90: min_pass=0.9, min_tika=0.9, max_low=0.6, min_avg=90.
LAYOUT_QUALITY_OVERRIDES = {
    "table": {
        "max_low_conf_ratio": 0.8,
        "min_pass_similarity": 0.75,
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 90.0,
    },
    "noisy": {
        "max_low_conf_ratio": 0.75,
        "min_pass_similarity": 0.75,
        "min_tika_similarity": 0.0,
        "min_avg_confidence": 92.0,
    },
    # Optional: slight relaxation for "text" when dual_pass is borderline
    "text": {
        "min_pass_similarity": 0.88,
    },
}
```

Merge rule in `_page_quality`: start from `quality_overrides` (or defaults); for each key in `LAYOUT_QUALITY_OVERRIDES.get(layout, {})`, apply override so we **relax only** (e.g. lower min_*, higher max_low_conf_ratio).
