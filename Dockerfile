FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fly routes external HTTPS traffic to this internal port (see fly.toml).
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
