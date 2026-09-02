FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    fonts-liberation \
    fontconfig \
    libreoffice-writer \
    poppler-utils \
    ca-certificates \
    git \
    curl \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Automation MCP yadisk is started as `uvx yadisk-mcp`. Preinstall so
# tool discovery does not download from PyPI at agent boot.
ENV UV_INSTALL_DIR=/usr/local/bin \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_CACHE_DIR=/opt/uv-cache
RUN curl -LsSf https://astral.sh/uv/0.12.9/install.sh | sh \
    && uv tool install yadisk-mcp==0.1.2 \
    && uvx yadisk-mcp --help
