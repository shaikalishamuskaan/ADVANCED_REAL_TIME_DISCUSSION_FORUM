FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/services/discussion
COPY services/discussion/requirements.txt services/discussion/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && useradd --uid 10001 --create-home app
COPY --chown=app:app services/discussion/ ./
COPY infrastructure/docker/runtime.py infrastructure/docker/healthcheck.py /app/docker/
COPY forum_logging/ /app/forum_logging/
USER app
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=6 CMD ["python", "/app/docker/healthcheck.py"]
ENTRYPOINT ["python", "/app/docker/runtime.py"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
