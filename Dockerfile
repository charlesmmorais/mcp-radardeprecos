FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Usuário sem privilégios.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV RADARDEPRECOS_TRANSPORT=streamable-http
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/', timeout=4).status==200 else 1)"]

CMD ["mcp-radardeprecos", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8080"]
