#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: train_tesseract.sh --lang <lang> --images <dir> --ground-truth <dir> [--output <dir>]

Required:
  --lang           Name of the trained model (e.g. eng_custom)
  --images         Directory with training images (png/jpg/tif)
  --ground-truth   Directory with matching .txt ground-truth files

Optional:
  --output         Output directory (default: training/output)

Notes:
  - Each image must have a matching .txt file with identical base name.
  - Requires tesseract training tools (lstmtraining, combine_tessdata).
EOF
}

LANG_NAME=""
IMAGES_DIR=""
GT_DIR=""
OUTPUT_DIR="$(pwd)/training/output"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang) LANG_NAME="$2"; shift 2 ;;
    --images) IMAGES_DIR="$2"; shift 2 ;;
    --ground-truth) GT_DIR="$2"; shift 2 ;;
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "$LANG_NAME" || -z "$IMAGES_DIR" || -z "$GT_DIR" ]]; then
  usage
  exit 1
fi

WORK_DIR="$(pwd)/training/work"
DATA_DIR="$WORK_DIR/data"
LIST_FILE="$WORK_DIR/list.txt"
mkdir -p "$OUTPUT_DIR" "$DATA_DIR"

TESSDATA_DIR="${TESSDATA_PREFIX:-/opt/homebrew/share/tessdata}"
BASE_LANG="eng"
START_MODEL="$TESSDATA_DIR/${BASE_LANG}.traineddata"
START_LSTM="$TESSDATA_DIR/${BASE_LANG}.lstm"

if [[ ! -f "$START_MODEL" || ! -f "$START_LSTM" ]]; then
  echo "Missing base model files at $TESSDATA_DIR"
  echo "Expected: $START_MODEL and $START_LSTM"
  exit 1
fi

rm -f "$LIST_FILE"

for img in "$IMAGES_DIR"/*.{png,jpg,jpeg,tif,tiff}; do
  [[ -e "$img" ]] || continue
  base="$(basename "$img")"
  name="${base%.*}"
  gt_file="$GT_DIR/$name.txt"
  if [[ ! -f "$gt_file" ]]; then
    echo "Missing ground-truth file for $img: $gt_file"
    exit 1
  fi
  cp "$img" "$DATA_DIR/$name.png"
  cp "$gt_file" "$DATA_DIR/$name.gt.txt"
  tesseract "$DATA_DIR/$name.png" "$DATA_DIR/$name" --psm 6 lstm.train >/dev/null 2>&1
  echo "$DATA_DIR/$name.lstmf" >> "$LIST_FILE"
done

if [[ ! -s "$LIST_FILE" ]]; then
  echo "No training images found."
  exit 1
fi

MODEL_PREFIX="$OUTPUT_DIR/$LANG_NAME"
CHECKPOINT="$MODEL_PREFIX"_checkpoint

lstmtraining \
  --model_output "$MODEL_PREFIX" \
  --continue_from "$START_LSTM" \
  --traineddata "$START_MODEL" \
  --train_listfile "$LIST_FILE" \
  --max_iterations 1000

lstmtraining \
  --stop_training \
  --continue_from "$CHECKPOINT" \
  --traineddata "$START_MODEL" \
  --model_output "$OUTPUT_DIR/$LANG_NAME.traineddata"

echo "Trained model saved to: $OUTPUT_DIR/$LANG_NAME.traineddata"
