# Linux image: the HTTP API only (the setup window and the Windows service are Windows-only).
#   docker build -t portrait-qa .
#   docker run -p 8080:8080 -v ./config.json:/config/config.json:ro portrait-qa
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORTRAIT_QA_CONFIG=/config/config.json
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY portrait_qa ./portrait_qa
RUN pip install --no-cache-dir . && useradd --system --uid 10001 portraitqa
USER portraitqa
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/v1/health', timeout=2)" || exit 1
# Inside a container the API must listen on all interfaces; set server.api_key in config.json.
CMD ["portrait-qa", "serve", "--host", "0.0.0.0", "--port", "8080", "--no-log-file"]
