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
# OLD: RUN pip install --no-cache-dir -e ".[all]"
# CHANGED (22 Nov 2026, before the first real Docker run).
# WHY: 1) "[all]" also installs the optional Docling / Camelot / OCR parsers. The project parses with PyMuPDF and
#         never used them, and they add several GB and many minutes to the build. "quality" (the real embedding
#         model and reranker) and "dev" (pytest, openpyxl) are what the app, the tests and the evaluation need.
#      2) On Linux, pip's default PyTorch brings the GPU libraries (several GB). The container runs on the CPU, so
#         the CPU build of PyTorch is installed first; the next line then finds torch already there.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -e ".[quality,dev]"

# Copy the rest of the project (config, app, ingest, eval, scripts, cert).
COPY . .

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
