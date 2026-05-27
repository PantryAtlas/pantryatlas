"""Test version and imports."""

import pantryatlas
import pantryatlas.data
import pantryatlas.embeddings
import pantryatlas.gemma
import pantryatlas.geometry
import pantryatlas.pantry
import pantryatlas.store


def test_version():
    """Test that version is correctly set."""
    assert pantryatlas.__version__ == "0.1.0"


def test_imports():
    """Test that subpackages can be imported."""
    # Verify all subpackages are importable
    assert pantryatlas.embeddings is not None
    assert pantryatlas.store is not None
    assert pantryatlas.gemma is not None
    assert pantryatlas.geometry is not None
    assert pantryatlas.pantry is not None
    assert pantryatlas.data is not None
