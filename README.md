# 📘 README.md — Zephyr Project Generator

> ✨ Generate a ready‑to‑build Zephyr application with one command, then build and flash with `west`.

## Table of Contents

* [Overview](#-overview)
* [Setup Zephyr (Official Docs)](#-setup-zephyr-official-docs)
* [Quick Start: Create an Application](#-quick-start-create-an-application)
* [Build & Flash](#-build--flash)
* [Project Layout](#-project-layout)
* [Troubleshooting](#-troubleshooting)
* [FAQ](#-faq)

## 🧭 Overview

This repository provides a simple Make target that scaffolds a Zephyr project by calling `zephyr_env.py`.
It fills in the typical files (`CMakeLists.txt`, `prj.conf`, devicetree overlay, folders, etc.) so you can jump straight to building.

Defaults (override any of these on the command line):

* `PRJ` — project name (default: `blink`)
* `FOLDER` — output folder (default: same as `PRJ`)
* `BOARD` — target board (default: `native_sim`)
* `OVERLAY` — devicetree overlay base name (default: `native_sim`)

## 🏗️ Setup Zephyr (Official Docs)

Follow the upstream getting‑started flow to prepare your toolchain & workspace.

1. Install host dependencies (CMake, Ninja, Python 3.10+, DTC, etc.).
2. Create and activate a Python virtual environment.

```bash
python3 -m venv ~/zephyrproject/.venv
. ~/zephyrproject/.venv/bin/activate
```

3. Install west:

```bash
pip install west
```

4. Fetch Zephyr sources:

```bash
west init ~/zephyrproject
cd ~/zephyrproject
west update
```

5. Export the CMake package:

```bash
west zephyr-export
```

6. Install extra Python requirements:

```bash
west packages pip --install
```

7. Install the Zephyr SDK (toolchains & host tools):

```bash
cd ~/zephyrproject/zephyr
west sdk install
```

8. (Optional) Smoke test with Blinky:

```bash
cd ~/zephyrproject/zephyr
west build -p always -b <your-board> samples/basic/blinky
west flash
```

## 🚀 Quick Start: Create an Application

From the root of this repository (where the `Makefile` and `zephyr_env.py` live), run:

```bash
make
```

This generates a new Zephyr app using the defaults shown above.

Then immediately build, run, clean, add a driver, and rebuild/run using the provided Make wrappers:

```bash
cd blink
make west-build
make west-run
```

Then to generate a sensor driver, define the parameter in the makefile in the app directory, then:

```bash
make clean
make add-driver
make west-build
make west-run
```

### Customize the app

Override any variable directly on the command line:

```bash
make PRJ=hello_world FOLDER=apps/hello BOARD=qemu_riscv64 OVERLAY=app
```

Then:

```bash
cd app
make add-driver
make west-build
make west-run
```

Examples:

* Native simulation (default):

```bash
make PRJ=blink_sim BOARD=native_sim OVERLAY=native_sim
```

Then:

```bash
cd app
make west-build
make west-run
make clean
make add-driver MODULE=sensirion_sht3xd_emul INTERFACE=i2c ADDRESS=44
make west-build
make west-run
```

* ESP32‑S3 DevKit (uncomment or set explicitly):

```bash
make PRJ=blink_esp FOLDER=apps/blink_esp BOARD=esp32s3_devkitc/esp32s3/procpu OVERLAY=esp32s3_devkitc
```

Then:

```bash
cd app
make west-build
make west-run
make clean
make add-driver MODULE=sensirion_sht3xd_emul INTERFACE=i2c ADDRESS=44
make west-build
make west-run
```

What the command runs under the hood:

```bash
python zephyr_env.py -p $(PRJ) -o $(FOLDER) -b $(BOARD) -y $(OVERLAY)
```

## 🧱 Build & Flash

Change into the newly created application folder:

```bash
cd <your-output-folder>
```

Build (with pristine) and flash using `west`:

```bash
west build -b <your-board> . -p auto
west flash
```

Tips:

* For `native_sim`, you can run the app directly:

```bash
west build -b native_sim . -p auto
west build -t run
```

* Add extra overlay or config:

```bash
west build -b <your-board> . -p auto -DDTC_OVERLAY_FILE=app.overlay -DOVERLAY_CONFIG=overlay.conf
```

## 🗂️ Project Layout

A typical generated app looks like:

```
<your-output-folder>/
├─ src/
├─ include/
├─ prj.conf
├─ app.overlay
├─ CMakeLists.txt
└─ Kconfig
```

## 🧯 Troubleshooting

* **Command not found:** Ensure your Zephyr environment is set up (see Setup section) and that you are running `make` in this repository’s root.
* **Board not supported:** Verify the board name matches Zephyr’s board ID and that the SDK for that architecture is installed.
* **Overlay or Kconfig errors:** Check the generated `app.overlay` and `prj.conf` for typos or conflicting options.
* **Existing files not overwritten:** Re‑run the generator with the overwrite flag at the script level if supported by your local `zephyr_env.py`.

## ❓ FAQ

**Do I need to use `west` after generation?**
Yes. The generator creates the project; you still build/flash with `west`.

**Where is the app generated?**
Inside `FOLDER` (defaults to the same name as `PRJ`).

**Can I regenerate with different options?**
Yes—either remove the output folder or use the script’s overwrite option if available.

---

Made with ❤️ for smoother Zephyr workflows.

