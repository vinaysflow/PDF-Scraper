# Diagram extraction – setup and troubleshooting

## What you need for VLM descriptions

1. **Figure extraction** works with just `pymupdf` (already in main dependencies). You get `figure` (page, bbox, area) and `reading.error` when the VLM is not used.

2. **Descriptions and structure** need the OpenAI client and an API key:
   - Install: `pip install openai`
   - Set your key: `export OPENAI_API_KEY=sk-your-key-here` (or set it in your shell profile / environment).

## If `pip install ".[diagrams]"` doesn’t work

Some terminals or shells (e.g. Windows cmd, some IDEs) don’t handle `".[diagrams]"` well. Use one of these instead:

**Option A – Install from project directory (recommended):**
```bash
cd /path/to/pdf-ocr-mvp
pip install .[diagrams]
```
(No quotes around `.[diagrams]`; try this first. If you get “invalid syntax” or “no such option”, use Option B.)

**Option B – Install OpenAI only:**
```bash
pip install openai
```
This is enough for diagram descriptions. The optional `.[diagrams]` extra only adds `openai`; your project already has `pymupdf`.

**Option C – With quotes (Unix/macOS/Linux):**
```bash
cd /path/to/pdf-ocr-mvp
pip install '.[diagrams]'
```

## Check that it works

```bash
cd pdf-ocr-mvp
source .venv/bin/activate   # or: .venv\Scripts\activate on Windows
python -c "import openai; print('openai OK')"
echo $OPENAI_API_KEY        # Unix/macOS: should show sk-... (Windows: use: echo %OPENAI_API_KEY%)
```

Then run extraction with diagram VLM:

```bash
python -m app.cli /path/to/file.pdf --extract-diagrams
```

If `OPENAI_API_KEY` is not set, you still get figure extraction; each `reading` will have `error: "VLM not configured"` or `"VLM describe failed"`.
