FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y \
    libreoffice \
    libreoffice-calc \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/school_portal

CMD gunicorn fola:app --bind 0.0.0.0:$PORT --workers 1 --timeout 180

