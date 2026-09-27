# ---- AI Product Mining & Complexity Cost Dashboard ----
FROM python:3.11-slim

ARG INSTALL_ML=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt && \
    if [ "$INSTALL_ML" = "true" ]; then \
      pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-ml.txt; \
    fi

COPY app ./app
COPY web ./web
COPY data/sample ./data/sample

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
