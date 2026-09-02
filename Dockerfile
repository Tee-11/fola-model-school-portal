```dockerfile
FROM python:3.13-slim

# Install LibreOffice and required components
RUN apt-get update && \
    apt-get install -y \
    libreoffice \
    libreoffice-calc \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy requirements first
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Create temporary folder
RUN mkdir -p /tmp/school_portal

# Render provides PORT automatically
CMD gunicorn fola:app --bind 0.0.0.0:$PORT --workers 1 --timeout 180
```

