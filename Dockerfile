FROM python:3.12-slim

# Security: run as non-root
RUN groupadd -r sweep && useradd -r -g sweep sweep

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config.yaml ./config.yaml

# Security: no root, read-only where possible
USER sweep

ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Cloud Run uses PORT env var
CMD ["python", "src/scanner.py"]
