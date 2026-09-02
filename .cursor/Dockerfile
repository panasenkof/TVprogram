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
