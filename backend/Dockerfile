FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# No torch/build-essential needed anymore — Gemini API handles embeddings
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --timeout 120 --workers 1 app:app
