# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/web
COPY web/package*.json ./
RUN npm install
COPY web/ .
RUN npm run build

# Stage 2: Runtime
FROM python:3.13-slim
WORKDIR /app

# Install system dependencies
# ffmpeg is useful for audio manipulation if jamarr does any transcoding or analysis
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Install Python dependencies with uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# Copy backend code and scripts (including DB migrations)
COPY app ./app
COPY scripts ./scripts

# Copy built frontend assets
COPY --from=frontend-builder /app/web/build ./web/build



# Expose port
EXPOSE 8111

# Command to run (host 0.0.0.0 is crucial for docker)
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8111", "--loop", "asyncio"]
