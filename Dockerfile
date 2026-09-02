# NeuroPipeline DICOM Converter — container image
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        pigz \
    && rm -rf /var/lib/apt/lists/*

# Install dcm2niix (static binary when available via package or GitHub release)
RUN apt-get update && apt-get install -y --no-install-recommends dcm2niix \
    || (curl -fsSL -o /tmp/dcm2niix.zip \
        https://github.com/rordenlab/dcm2niix/releases/latest/download/dcm2niix_lnx.zip \
        && apt-get install -y --no-install-recommends unzip \
        && unzip /tmp/dcm2niix.zip -d /usr/local/bin \
        && chmod +x /usr/local/bin/dcm2niix \
        && rm -f /tmp/dcm2niix.zip) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY configs ./configs
COPY templates ./templates

RUN pip install --upgrade pip \
    && pip install . \
    && useradd --create-home --shell /bin/bash neuro \
    && chown -R neuro:neuro /app

USER neuro
ENTRYPOINT ["python", "-m", "neuro_pipeline"]
CMD ["--help"]
