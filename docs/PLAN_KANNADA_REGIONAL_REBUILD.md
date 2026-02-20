# Plan: Kannada + Regional Languages Rebuild

**Status:** Implemented. This doc records the plan that was executed.

**Summary of changes:**

- **Language config and router** ([app/ocr_router.py](pdf-ocr-mvp/app/ocr_router.py)): `LANGUAGE_PROFILES` (english, kannada, hindi, tamil, telugu), alias map, `resolve_ocr_config(language, ocr_lang)` returning `ResolvedOCRConfig`.
- **Extract pipeline** ([app/extract.py](pdf-ocr-mvp/app/extract.py)): Router called at start; `resolved.tesseract_lang` for Tesseract; `resolved.paddleocr_lang` for Paddle (Paddle skipped when `None`); `LANGUAGE_QUALITY_OVERRIDES` (kannada, default) merged into `quality_overrides`; `extraction.language` set in response.
- **API** ([app/api.py](pdf-ocr-mvp/app/api.py)): `language` and `ocr_lang` as Form params on all three extract endpoints; passed to worker for async.
- **CLI** ([app/cli.py](pdf-ocr-mvp/app/cli.py)): `--language` argument; passed to `extract_pdf`.
- **UI** ([static/index.html](pdf-ocr-mvp/static/index.html), [public/index.html](pdf-ocr-mvp/public/index.html)): "Document language" dropdown (English, Kannada, Hindi, Tamil, Telugu) first in options; `language` sent on every request; result summary shows Language when present.
- **Schema** ([app/schema.py](pdf-ocr-mvp/app/schema.py)): `ExtractionMetadata.language` added.
- **Docker**: `tesseract-ocr-kannada` in Dockerfile.
- **Docs**: [DISCOVERY_KARNATAKA_KANNADA.md](DISCOVERY_KARNATAKA_KANNADA.md) updated with sample run; optional [scripts/kannada_sample_extract.py](../scripts/kannada_sample_extract.py).

**Sample run:**

```bash
python -m app.cli "/path/to/Kannada SL.pdf" --language kannada --force-ocr --max-pages 10
# Or use the script (default path: ~/Downloads/Kannada SL.pdf):
python scripts/kannada_sample_extract.py
python scripts/kannada_sample_extract.py "/path/to/other.pdf"
```
