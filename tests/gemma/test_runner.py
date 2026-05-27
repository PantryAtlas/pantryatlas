"""Tests for epicure_core.gemma.runner.GemmaRunner.

All subprocess and httpx calls are mocked — no live llama-server or model
is required to run this test module.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from epicure_core.gemma.runner import GemmaRunner, MemoryPressureError


# ---------------------------------------------------------------------------
# AC-4: E4B selected when free RAM >= 6 GiB
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_select_e4b_when_ram_high(mock_vmem):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    r = GemmaRunner()
    assert r._selected_model == "E4B"


# ---------------------------------------------------------------------------
# AC-5: E2B selected when free RAM < 6 GiB
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_select_e2b_when_ram_low(mock_vmem):
    mock_vmem.return_value = MagicMock(available=4 * 1024**3)
    r = GemmaRunner()
    assert r._selected_model == "E2B"


# ---------------------------------------------------------------------------
# AC-6: is_healthy() returns False when subprocess is dead
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_is_healthy_false_when_subprocess_dead(mock_vmem):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    r = GemmaRunner()
    r._proc = MagicMock()
    r._proc.poll.return_value = 1  # exited with code 1
    assert r.is_healthy() is False


# ---------------------------------------------------------------------------
# AC-7: GemmaRunner is a valid context manager (__enter__ / __exit__)
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_context_manager_shape(mock_vmem):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    with (
        patch.object(GemmaRunner, "start", autospec=True) as mock_start,
        patch.object(GemmaRunner, "stop", autospec=True) as mock_stop,
    ):
        with GemmaRunner() as r:
            assert isinstance(r, GemmaRunner)
        mock_start.assert_called_once()
        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# AC-8: subprocess is terminated on context exit (no orphan PIDs)
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_subprocess_terminated_on_exit(mock_vmem):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    r = GemmaRunner()
    fake_proc = MagicMock()
    fake_proc.poll.side_effect = [None, 0]  # first: running; second: dead
    fake_proc.wait.return_value = 0
    r._proc = fake_proc
    r.stop()
    fake_proc.terminate.assert_called_once()
    assert r._proc is None


# ---------------------------------------------------------------------------
# AC-9: first-start writes baseline-tps.json with required keys
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_baseline_tps_written(mock_vmem, tmp_path, monkeypatch):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    monkeypatch.setattr("epicure_core.gemma.runner.EPICURE_HOME", tmp_path)
    monkeypatch.setattr(
        "epicure_core.gemma.runner.BASELINE_TPS_PATH", tmp_path / "baseline-tps.json"
    )
    r = GemmaRunner()
    with patch.object(r, "_measure_tps", return_value=12.5):
        r._maybe_record_baseline()
    data = json.loads((tmp_path / "baseline-tps.json").read_text())
    assert data["tokens_per_second"] == 12.5
    assert data["model"] == "E4B"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Extra: MemoryPressureError raised when runner.blocked flag exists
# ---------------------------------------------------------------------------


@patch("epicure_core.gemma.runner.psutil.virtual_memory")
def test_memory_pressure_error_when_blocked(mock_vmem, tmp_path, monkeypatch):
    mock_vmem.return_value = MagicMock(available=7 * 1024**3)
    monkeypatch.setattr(
        "epicure_core.gemma.runner.RUNNER_BLOCKED_FLAG", tmp_path / "runner.blocked"
    )
    (tmp_path / "runner.blocked").write_text("blocked by mem-monitor")
    r = GemmaRunner()
    with pytest.raises(MemoryPressureError):
        r._check_block_flag()
