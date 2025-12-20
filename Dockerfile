# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies
# ffmpeg is useful for audio manipulation if jamarr does any transcoding or analysis
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY app ./app

# Copy built frontend assets
COPY --from=frontend-builder /app/web/build ./web/build

# Copy management scripts
COPY scan.py .

# Expose port
EXPOSE 8111

# Command to run (host 0.0.0.0 is crucial for docker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8111"]
