# Running CodeGen with Docker

## Requirements

Install [Docker Desktop](https://www.docker.com/get-started/) (Windows, macOS or Linux).

## Setup

1. Create an `inputs/` and an `outputs/` folder in your working directory.
2. Place your JSON configuration file inside `inputs/`.

## Pull the image

```bash
docker pull ghcr.io/sampleenvironment/secop-plc:master
```

## Run CodeGen

**macOS / Linux**
```bash
docker run --rm \
  -v "$(pwd)/inputs:/app/inputs" \
  -v "$(pwd)/outputs:/app/outputs" \
  ghcr.io/sampleenvironment/secop-plc:master \
  --config inputs/your_config.json --out outputs
```

**Windows (PowerShell)**
```powershell
docker run --rm `
  -v "${PWD}/inputs:/app/inputs" `
  -v "${PWD}/outputs:/app/outputs" `
  ghcr.io/sampleenvironment/secop-plc:master `
  --config inputs/your_config.json --out outputs
```

Replace `your_config.json` with the name of your configuration file. Generated files will appear in the `outputs/` folder.

## Notes

- The image is automatically rebuilt and published on every push to `master`.
- To use a specific version instead of the latest, replace `:master` with the corresponding tag (e.g. `:sha256-abc123`).