"""Memory-pressure monitor daemon.

Watches psutil.virtual_memory().percent in a loop. When pressure crosses the
HIGH threshold (default 85%), writes a flag file that GemmaRunner.start()
checks before launching llama-server. When pressure drops back below the LOW
threshold (default 75%), removes the flag.

Run as a systemd service: see ops/systemd/epicure-mem-monitor.service.
"""

import argparse
import time
from pathlib import Path

import psutil

DEFAULT_FLAG_PATH = Path.home() / ".epicure" / "runner.blocked"
DEFAULT_HIGH_PCT = 85.0
DEFAULT_LOW_PCT = 75.0
DEFAULT_INTERVAL_S = 5.0


def tick(
    flag_path: Path = DEFAULT_FLAG_PATH,
    high_pct: float = DEFAULT_HIGH_PCT,
    low_pct: float = DEFAULT_LOW_PCT,
) -> bool:
    """One monitoring tick.

    Returns True if the flag was written or is still present after this tick;
    False if the flag was removed or absent.
    """
    pct = psutil.virtual_memory().percent
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    if pct >= high_pct:
        if not flag_path.exists():
            flag_path.write_text(
                f"mem.percent={pct:.1f} crossed high threshold {high_pct}\n"
            )
        return True
    if pct < low_pct and flag_path.exists():
        flag_path.unlink()
        return False
    return flag_path.exists()


def run_loop(
    flag_path: Path = DEFAULT_FLAG_PATH,
    high_pct: float = DEFAULT_HIGH_PCT,
    low_pct: float = DEFAULT_LOW_PCT,
    interval_s: float = DEFAULT_INTERVAL_S,
) -> None:
    """Run the monitor forever. Intended for systemd."""
    while True:
        tick(flag_path, high_pct, low_pct)
        time.sleep(interval_s)


def main() -> None:
    """Entry point for the memory-pressure monitor daemon."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--high-pct", type=float, default=DEFAULT_HIGH_PCT)
    parser.add_argument("--low-pct", type=float, default=DEFAULT_LOW_PCT)
    parser.add_argument("--interval-s", type=float, default=DEFAULT_INTERVAL_S)
    args = parser.parse_args()
    run_loop(high_pct=args.high_pct, low_pct=args.low_pct, interval_s=args.interval_s)


if __name__ == "__main__":
    main()
