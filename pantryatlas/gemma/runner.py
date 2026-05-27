"""GemmaRunner: lifecycle manager for a llama.cpp server subprocess.

Auto-selects E4B (6 GiB+ free) or E2B (fallback) at construction time.
Use as a context manager; downstream clients talk to ``runner.url``.
"""

import json
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import psutil

ModelTier = Literal["E4B", "E2B"]

PANTRYATLAS_HOME = Path.home() / ".pantryatlas"
BASELINE_TPS_PATH = PANTRYATLAS_HOME / "baseline-tps.json"
MODELS_DIR = Path.home() / "pantryatlas" / "models"
DEFAULT_LLAMA_SERVER = Path.home() / "pantryatlas" / "llama.cpp" / "build" / "bin" / "llama-server"
RUNNER_BLOCKED_FLAG = PANTRYATLAS_HOME / "runner.blocked"

E4B_GGUF_NAME = "gemma-4-E4B-it-Q4_K_M.gguf"
E2B_GGUF_NAME = "gemma-4-E2B-it-Q4_K_M.gguf"
E4B_MEMORY_FLOOR_GB: float = 6.0


class MemoryPressureError(RuntimeError):
    """Raised when GemmaRunner refuses to start due to memory pressure."""


class GemmaRunner:
    """Manages a llama.cpp server subprocess for Gemma 4.

    Auto-selects E4B vs E2B at construction based on free RAM.  Use as a
    context manager::

        with GemmaRunner() as r:
            r.is_healthy()  # True
            # downstream GemmaClient (T-011/T-012) talks to r.url

    Parameters
    ----------
    llama_server_path:
        Path to the ``llama-server`` binary.  Defaults to the path laid down
        by the T-009 bootstrap script.
    models_dir:
        Directory that contains the GGUF files.
    e4b_floor_gb:
        Minimum free RAM in GiB required to prefer E4B over E2B.
    port:
        TCP port for the llama-server HTTP API.  A free ephemeral port is
        chosen automatically when *None*.
    startup_timeout_s:
        Seconds to wait for the server to become healthy after launch.
    """

    def __init__(
        self,
        llama_server_path: Path | None = None,
        models_dir: Path | None = None,
        e4b_floor_gb: float = E4B_MEMORY_FLOOR_GB,
        port: int | None = None,
        startup_timeout_s: float = 60.0,
    ) -> None:
        self._llama_server = llama_server_path or DEFAULT_LLAMA_SERVER
        self._models_dir = models_dir or MODELS_DIR
        self._port = port or self._find_free_port()
        self._startup_timeout = startup_timeout_s
        self._selected_model: ModelTier = self._select_model(e4b_floor_gb)
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._url = f"http://127.0.0.1:{self._port}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @staticmethod
    def _select_model(floor_gb: float) -> ModelTier:
        available_gb = psutil.virtual_memory().available / (1024**3)
        return "E4B" if available_gb >= floor_gb else "E2B"

    def _check_block_flag(self) -> None:
        if RUNNER_BLOCKED_FLAG.exists():
            raise MemoryPressureError(
                f"Runner blocked by memory monitor: remove {RUNNER_BLOCKED_FLAG} to unblock."
            )

    def _wait_for_ready(self) -> None:
        deadline = time.time() + self._startup_timeout
        while time.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                code = self._proc.returncode if self._proc else "N/A"
                raise RuntimeError(
                    f"llama-server died during startup; exit code {code}"
                )
            try:
                r = httpx.get(f"{self._url}/health", timeout=1.0)
                if r.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                time.sleep(0.5)
        raise TimeoutError(
            f"llama-server did not become healthy in {self._startup_timeout}s"
        )

    def _measure_tps(self) -> float:
        """Send a 32-token completion and return tokens/second."""
        t0 = time.perf_counter()
        r = httpx.post(
            f"{self._url}/completion",
            json={"prompt": "Hello", "n_predict": 32, "temperature": 0.0},
            timeout=60.0,
        )
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            return 0.0
        return 32.0 / elapsed if elapsed > 0 else 0.0

    def _maybe_record_baseline(self) -> None:
        """Write baseline-tps.json on the first-ever server start."""
        if BASELINE_TPS_PATH.exists():
            return
        tps = self._measure_tps()
        PANTRYATLAS_HOME.mkdir(parents=True, exist_ok=True)
        BASELINE_TPS_PATH.write_text(
            json.dumps(
                {
                    "tokens_per_second": tps,
                    "model": self._selected_model,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                indent=2,
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        """Base URL of the running llama-server (e.g. ``http://127.0.0.1:8080``)."""
        return self._url

    @property
    def model(self) -> ModelTier:
        """Which model tier was selected at construction time."""
        return self._selected_model

    def is_healthy(self) -> bool:
        """Return True iff the subprocess is alive and /health responds 200."""
        if self._proc is None or self._proc.poll() is not None:
            return False
        try:
            r = httpx.get(f"{self._url}/health", timeout=2.0)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def start(self) -> None:
        """Launch the llama-server subprocess and block until healthy."""
        if self._proc is not None:
            return  # idempotent
        self._check_block_flag()
        gguf_name = E4B_GGUF_NAME if self._selected_model == "E4B" else E2B_GGUF_NAME
        gguf = self._models_dir / gguf_name
        if not gguf.exists():
            raise FileNotFoundError(
                f"GGUF not found at {gguf}; run ops/pi-bootstrap.sh to download it."
            )
        cmd = [
            str(self._llama_server),
            "-m",
            str(gguf),
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port),
            "-c",
            "8192",
            "--threads",
            str(max(1, psutil.cpu_count(logical=False) - 1)),
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._wait_for_ready()
        self._maybe_record_baseline()

    def stop(self) -> None:
        """Terminate the subprocess (SIGTERM → SIGKILL after 5 s)."""
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "GemmaRunner":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        self.stop()
