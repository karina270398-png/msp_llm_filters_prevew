# MCP LLM Courts - Application Dockerfile
# Base: Python 3.11 slim image
FROM python:3.11-slim

# System deps (certs, curl for healthchecks, gcc if wheels need building)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY prompts /app/prompts

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Expose app port
EXPOSE 8000

# Env defaults (can be overridden by compose/.env)
ENV UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

# Start the web app
CMD ["uvicorn", "msp_llm_filters.webapp:app", "--host", "0.0.0.0", "--port", "8000"]
