# CodeGen (Docker)

## Requirements

Install Docker:

https://www.docker.com/get-started/

---

## Setup

1. **Clone or download this repository**:

```bash
git clone https://github.com/SampleEnvironment/SECoP-PLC.git
```

or download it as a ZIP from GitHub and extract it.

---

2. **Navigate to the `code-generator` folder (the one containing the Dockerfile)**:

```bash
cd SECoP-PLC/code-generator
```

> Note: the exact path may vary depending on how you downloaded the repository.
> Make sure you are in the folder that contains the `Dockerfile`.

---

3. **Verify you are in the correct folder**

You should see files like:

```text
Dockerfile
requirements.txt
src/
```

---

4. **Create the following folders if they do not exist**:

```text
inputs/
outputs/
```

---

5. **Place your JSON configuration file inside the `inputs/` folder**

---

## Build the Docker image

Run this command from the folder containing the `Dockerfile`:

```bash
docker build -t codegen:1.0 .
```

---

## Run CodeGen

### macOS / Linux

```bash
docker run --rm -v "$(pwd)/inputs:/work/inputs:ro" -v "$(pwd)/outputs:/work/outputs" codegen:1.0 --config /work/inputs/your_config.json --out /work/outputs
```

### Windows (PowerShell)

```powershell
docker run --rm -v "${PWD}\inputs:/work/inputs:ro" -v "${PWD}\outputs:/work/outputs" codegen:1.0 --config /work/inputs/your_config.json --out /work/outputs
```

---

## Output

All generated files will be available in the `outputs/` folder.

---

## Notes

* Replace `your_config.json` with the name of your configuration file.
* Paths inside the container must always use `/`, not `\`.
* The `inputs` folder is mounted as read-only.
* Make sure you run all commands from the folder containing the `Dockerfile`.
