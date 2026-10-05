FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY backend/requirements.txt backend/requirements-daytona.txt backend/requirements-browser.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-daytona.txt -r /tmp/requirements-browser.txt && python -m playwright install --with-deps chromium
COPY backend/app /app/backend/app
COPY backend/migrations /app/backend/migrations
COPY backend/alembic.ini /app/backend/alembic.ini
RUN useradd --create-home openlearn && mkdir -p /app/backend/data && chown -R openlearn:openlearn /app
USER openlearn
CMD ["python","-m","backend.app.hosted_runtime","api"]
