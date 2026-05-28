# Installing PantryAtlas on Raspberry Pi 5

This guide walks you through setting up **PantryAtlas** on a fresh Raspberry Pi 5 for use in community kitchens, test labs, or personal food exploration projects. The full bootstrap takes about **30 minutes** from power-on to "ready to code."

We assume you're comfortable with the Linux shell and have basic networking (Ethernet or WiFi). You'll need one command: `bash ops/pi-bootstrap.sh`.

## What you need

- **Raspberry Pi 5** with **8GB RAM** (6GB may work; 4GB will not)
- **32GB+ SD card** (64GB or larger recommended for recipe storage)
- **Raspberry Pi OS Bookworm 64-bit** (latest as of the installation date)
- **Power supply**: 27W USB-C recommended; 5A minimum
- **Ethernet or WiFi**: Kernel updates and model weights download require network access
- **SSH client** on your workstation (for headless setup)

### Network note

The bootstrap script downloads ~2GB of model weights (Gemma 4 GGUF + bge-m3 ONNX model). On a 5 Mbps connection, this is ~30 min. On gigabit, ~30 sec. Plan accordingly.

## Step 1: Flash the SD card

1. Download **Raspberry Pi Imager** from [https://www.raspberrypi.com/software/](https://www.raspberrypi.com/software/)
2. Insert the SD card into your workstation
3. Open Raspberry Pi Imager
   - **Device**: Raspberry Pi 5
   - **OS**: Raspberry Pi OS (64-bit) — pick the latest Bookworm release
   - **Storage**: select your SD card
4. Click **Next**, then **Edit Settings**:
   - Hostname: `pi` (or your choice; examples below use `pi`)
   - Username: `pi`, password: your choice
   - WiFi: configure if not using Ethernet
   - Check "Set locale settings" → timezone + keyboard
5. Click **Save**, then **Yes** to write (2–3 min)
6. Eject the card and insert it into the Pi 5

## Step 2: First boot — basic Pi setup

1. **Power on** the Pi and wait 30 seconds for first boot
2. **SSH in** from your workstation:
   ```bash
   ssh pi@raspberrypi.local
   ```
   or if you chose a different hostname:
   ```bash
   ssh pi@YOUR_HOSTNAME.local
   ```
3. **Update the system**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
   This takes 5–10 min on first run.
4. **Install git**:
   ```bash
   sudo apt install git -y
   ```

Your Pi is now ready. You have ≥6GB free RAM and a current package index.

## Step 3: Run pi-bootstrap.sh

The bootstrap script is idempotent: safe to re-run if interrupted.

```bash
git clone https://github.com/pantryatlas/pantryatlas.git ~/pantryatlas
bash ~/pantryatlas/ops/pi-bootstrap.sh
```

The script will:
1. Install build tools (cmake, gcc, python3-venv, sqlite3)
2. Create a Python venv at `~/pantryatlas/venv`
3. Clone and build llama.cpp with ARM64 optimizations
4. Download the Gemma 4 E4B model weights (~2GB)
5. Install pantryatlas in editable mode

Expected time: **20–30 minutes**. You'll see progress like:

```
[pi-bootstrap] Installing apt dependencies...
[pi-bootstrap] Creating venv at /home/pi/pantryatlas/venv...
[pi-bootstrap] Cloning llama.cpp...
[pi-bootstrap] Building llama.cpp (this may take 10 min)...
[pi-bootstrap] Downloading Gemma 4 GGUF...
[pi-bootstrap] Installing pantryatlas...
BOOTSTRAP COMPLETE
```

If the script exits with an error, read the error message (usually a missing network connection or full disk). Fix the issue and re-run `bash ~/pantryatlas/ops/pi-bootstrap.sh` — it will skip completed steps.

### What if you don't have 8GB?

- **6GB RAM**: Change `E4B_MEMORY_FLOOR_GB=6` in the runner config. The model will swap slightly; expect +1–2 sec latency.
- **4GB RAM**: Not supported in v0.1. E2B (smaller model) is deferred to v0.2.

### What if the script is not found?

If you see `pi-bootstrap.sh: No such file or directory`, try:
```bash
ls -la ~/pantryatlas/ops/
```

If `ops/` is missing, your clone failed. Try again:
```bash
rm -rf ~/pantryatlas
git clone https://github.com/pantryatlas/pantryatlas.git ~/pantryatlas
```

## Step 4: Verify the installation

1. **Activate the venv**:
   ```bash
   source ~/pantryatlas/venv/bin/activate
   ```
   (You'll see `(venv)` in your prompt.)

2. **Check the version**:
   ```bash
   python -c "import pantryatlas; print(pantryatlas.__version__)"
   ```
   Should print `0.1.0.dev0`.

3. **Run the integration test**:
   ```bash
   pytest -q ~/pantryatlas/tests/
   ```
   All tests should pass. (If running for the first time, Gemma 4 will load; expect 10–15 sec per test that uses the model.)

4. **Try a quick embedding**:
   ```bash
   python << 'EOF'
   from pantryatlas import embeddings
   vecs = embeddings.embed(["tomato", "tomate"])
   print(f"Embedded {len(vecs)} vectors")
   print(f"Cosine similarity: {(vecs[0] @ vecs[1]):.3f}")
   EOF
   ```
   You should see a similarity close to 0.95 (tomato and tomate are the same word in Spanish).

## Persistent setup (optional)

If you plan to use `pantryatlas` regularly, add the venv to your shell startup:

```bash
echo 'export PATH="$HOME/pantryatlas/venv/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Now you can use `python`, `pytest`, etc. without typing the full venv path.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No space left on device` during build | SSH in and run `df -h`. If `/` is full, you may need a larger SD card. |
| `ModuleNotFoundError: No module named 'pantryatlas'` | Make sure the venv is activated: `source ~/pantryatlas/venv/bin/activate`. |
| `Gemma 4 download timeout` | Restart the bootstrap script; it will resume. |
| `poetry: command not found` | The script uses pip, not poetry. If you see this, `pip install poetry` was erroneously run; it's not needed. |

## Next steps

- Read the **[API Reference](api.md)** to learn the public API
- Try the **[Pantry quickstart](../examples/pantry_quickstart.py)** (if examples/ exists)
- Join the discussion at **[github.com/pantryatlas/pantryatlas](https://github.com/pantryatlas/pantryatlas)**

---

**Still stuck?** Open an issue at [github.com/pantryatlas/pantryatlas/issues](https://github.com/pantryatlas/pantryatlas/issues) with the full output of `bash ~/pantryatlas/ops/pi-bootstrap.sh`.
