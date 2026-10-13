FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
RUN useradd --create-home --gid voice voice
USER voice
RUN python agent.py download-files
CMD ["python", "agent.py", "start"]
