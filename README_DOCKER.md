# Docker / Compose usage

## Build

```bash
docker build -t neuropipeline .
```

## Convert (mount data)

```bash
docker run --rm \
  -v /path/to/data:/data \
  neuropipeline convert \
  --input /data/dicoms \
  --output /data/niftis
```

Batch mode (subject subfolders under input):

```bash
docker run --rm \
  -v /path/to/data:/data \
  neuropipeline convert \
  --input /data/dicoms \
  --output /data/niftis \
  --batch
```

## Compose

```bash
export HOST_DATA=/path/to/data
docker compose run --rm neuropipeline convert --input /data/input --output /data/output --batch
```

No study-specific paths are baked into the image.
