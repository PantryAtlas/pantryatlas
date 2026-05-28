from pantryatlas.inference.config import (
    ProviderConfig,
    load_provider_config,
    save_provider_config,
)


def test_load_missing_returns_default_local(tmp_path):
    cfgs = load_provider_config(tmp_path / "nope.json")
    assert len(cfgs) == 1
    assert cfgs[0].kind == "local"
    assert cfgs[0].capabilities == ["text"]


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "providers.json"
    original = [
        ProviderConfig(name="on-board", kind="local", priority=100),
        ProviderConfig(
            name="desktop", kind="lan", priority=10,
            base_url="http://192.168.1.50:8080", capabilities=["text", "vision"],
        ),
    ]
    save_provider_config(original, path)
    loaded = load_provider_config(path)
    assert loaded == original
