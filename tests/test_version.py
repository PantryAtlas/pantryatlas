"""Test version and imports."""

import epicure_core
import epicure_core.data
import epicure_core.embeddings
import epicure_core.gemma
import epicure_core.geometry
import epicure_core.pantry
import epicure_core.store


def test_version():
    """Test that version is correctly set."""
    assert epicure_core.__version__ == "0.1.0.dev0"


def test_imports():
    """Test that subpackages can be imported."""
    # Verify all subpackages are importable
    assert epicure_core.embeddings is not None
    assert epicure_core.store is not None
    assert epicure_core.gemma is not None
    assert epicure_core.geometry is not None
    assert epicure_core.pantry is not None
    assert epicure_core.data is not None
