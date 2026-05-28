from unittest.mock import MagicMock, patch

import pytest

from pantryatlas.ops.mem_monitor import tick


def test_tick_writes_flag_when_high(tmp_path):
    flag = tmp_path / "runner.blocked"
    with patch("pantryatlas.ops.mem_monitor.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(percent=90.0)
        assert tick(flag_path=flag, high_pct=85.0, low_pct=75.0) is True
    assert flag.exists()
    assert "90.0" in flag.read_text()


def test_tick_removes_flag_when_low(tmp_path):
    flag = tmp_path / "runner.blocked"
    flag.write_text("preexisting flag")
    with patch("pantryatlas.ops.mem_monitor.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(percent=60.0)
        assert tick(flag_path=flag, high_pct=85.0, low_pct=75.0) is False
    assert not flag.exists()


def test_tick_hysteresis_keeps_flag_between_thresholds(tmp_path):
    flag = tmp_path / "runner.blocked"
    flag.write_text("preexisting flag")
    with patch("pantryatlas.ops.mem_monitor.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(percent=80.0)  # between low (75) and high (85)
        # flag should stay because we're not below low_pct
        assert tick(flag_path=flag, high_pct=85.0, low_pct=75.0) is True
    assert flag.exists()


def test_gemma_runner_raises_on_block_flag(tmp_path, monkeypatch):
    from pantryatlas.gemma.runner import GemmaRunner, MemoryPressureError

    monkeypatch.setattr(
        "pantryatlas.gemma.runner.RUNNER_BLOCKED_FLAG", tmp_path / "runner.blocked"
    )
    (tmp_path / "runner.blocked").write_text("blocked")
    with patch("pantryatlas.gemma.runner.psutil.virtual_memory") as mock_vm:
        mock_vm.return_value = MagicMock(available=7 * 1024**3)
        r = GemmaRunner()
        with pytest.raises(MemoryPressureError):
            r.start()
