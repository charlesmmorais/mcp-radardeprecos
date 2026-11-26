# Imagens fixadas pelo digest; o Dependabot atualiza tag e digest juntos.
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# Só o que está no uv.lock, com o hash de cada pacote conferido, e nenhuma
# dependência compilada a partir do código-fonte (--no-build).
RUN uv sync --locked --no-dev --extra metrics --no-build --no-editable \
    && rm /usr/local/bin/uv
ENV PATH="/app/.venv/bin:$PATH"

# Usuário sem privilégios.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

ENV RADARDEPRECOS_TRANSPORT=streamable-http
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/', timeout=4).status==200 else 1)"]

CMD ["mcp-radardeprecos", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8080"]
