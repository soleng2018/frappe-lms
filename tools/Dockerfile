ARG TOOLS_PYTHON_IMAGE
FROM ${TOOLS_PYTHON_IMAGE}
COPY --from=ghcr.io/astral-sh/uv:0.5.31@sha256:7bff3c3776ec467fc1437960f2c469d8beb30f536a6465a3350c647ccd260ec2 /uv /usr/local/bin/uv
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
