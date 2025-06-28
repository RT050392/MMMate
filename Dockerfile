FROM python:3.11-slim

# Install system dependencies for OCR and PDF
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY . /app
WORKDIR /app

# Cloud Run expects the app to listen on $PORT
ENV PORT=8080

# Start app with Gunicorn (replace app:app if your filename/app is different)
CMD exec gunicorn --bind :$PORT --workers 1 --timeout 120 app:app
