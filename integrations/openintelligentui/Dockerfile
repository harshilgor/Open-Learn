FROM node:24-bookworm-slim AS node-runtime
FROM python:3.12-slim-bookworm
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY backend/requirements.txt backend/requirements-browser.txt backend/requirements-daytona.txt /app/backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-browser.txt -r backend/requirements-daytona.txt uv==0.9.21 \
    && python -m playwright install --with-deps chromium
COPY integrations/openintelligentui/package*.json /app/integrations/openintelligentui/
RUN cd integrations/openintelligentui && npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY integrations/openintelligentui/upstream/apps/agent/pyproject.toml integrations/openintelligentui/upstream/apps/agent/uv.lock /opt/agent-project/
RUN cd /opt/agent-project && UV_PROJECT_ENVIRONMENT=/opt/visual-agent uv sync --frozen --no-dev --no-install-project
COPY backend /app/backend
COPY integrations/openintelligentui /app/integrations/openintelligentui
ENV PYTHONUNBUFFERED=1 COPILOTKIT_TELEMETRY_DISABLED=true LANGSMITH_TRACING=false OPENLEARN_WORKER_MODE=embedded
RUN useradd --create-home openlearn && mkdir -p /app/backend/data && chown openlearn:openlearn /app/backend/data
USER openlearn
EXPOSE 8000
CMD ["python", "integrations/openintelligentui/serve.py"]
