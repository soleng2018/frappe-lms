ARG TOOLS_PYTHON_IMAGE
FROM ${TOOLS_PYTHON_IMAGE}
COPY --from=ghcr.io/astral-sh/uv:0.5.31 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache \
    HOME=/tmp \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev && chmod -R a+rX /opt/venv
ENTRYPOINT ["tools"]
