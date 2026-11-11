# App container for the Streamlit chat.
FROM python:3.11-slim

# System deps for PDF parsing + OCR (poppler for pdf2image, tesseract for OCR).
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        ghostscript \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (layer cached until pyproject.toml changes).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[all]"

# Copy the rest of the project (config, app, ingest, eval, scripts, cert).
COPY . .

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
