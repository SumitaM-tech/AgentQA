# Backend: FastAPI + Playwright + Chromium. The official Playwright image already contains Chromium and its
# system libraries (version must match playwright in requirements.txt).
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

COPY . .
# Artifacts live on a volume owned by the unprivileged user shipped with the image.
RUN mkdir -p /data/artifacts && chown -R pwuser:pwuser /data /app
USER pwuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# Apply migrations, then start a SINGLE worker (the live-event bus is in-process; one browser at a time).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
