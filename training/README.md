# OCR Training Workflow

This folder contains scripts and notes to train a custom Tesseract model using
your labeled data (images + ground-truth text).

## Requirements

- Homebrew-installed `tesseract` with training tools
- `make`, `bash`, and standard build utilities

Install tools:

```
brew install tesseract
```

If training tools are missing, install the tesstrain repo:

```
git clone https://github.com/tesseract-ocr/tesstrain.git
```

## Data Layout

Provide training data as:

```
training/data/
  images/
    0001.png
    0002.png
  gt/
    0001.txt
    0002.txt
```

Each `.txt` file should contain the exact text for the matching image. For tables,
prefer tab-separated values in row order so OCR learns column alignment.

Example (cell text in row order):

```
Col1\tCol2\tCol3
12\t34\t56
```

## Training

From repo root:

```
bash training/train_tesseract.sh \
  --lang eng_custom \
  --images training/data/images \
  --ground-truth training/data/gt \
  --tesstrain-path /path/to/tesstrain
```

The script produces a `*.traineddata` file in `training/output/`.

## Using the trained model

Set the Tesseract data path and language in CLI/API:

```
python -m app.cli /path/to/file.pdf --ocr-lang eng_custom --tessdata-path /path/to/traineddata
```

Or set `TESSDATA_PREFIX` in your environment.
