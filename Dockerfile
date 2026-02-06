# Backend for PDF OCR (for Railway / Render / Fly.io)
# Requires: tesseract, poppler-utils, openjdk (for Tika), libs for OpenCV

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    openjdk-21-jre-headless \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -e .

ENV PORT=8000
EXPOSE 8000
CMD uvicorn app.api:app --host 0.0.0.0 --port ${PORT}
