FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir 'mcp[cli]>=1.0' httpx

COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
