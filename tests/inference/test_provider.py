from pantryatlas.inference.provider import (
    CapabilityUnavailable,
    NoProviderAvailable,
    Provider,
    ProviderInfo,
)


class _Dummy:
    name = "dummy"
    kind = "lan"
    capabilities = {"text"}
    priority = 10
    enabled = True

    def is_available(self) -> bool:
        return True

    def force_probe(self) -> bool:
        return True

    def generate(self, system, user, **kwargs):
        return "ok"

    def vision_generate(self, image_bytes, prompt, system):
        raise CapabilityUnavailable("vision")

    def info(self):
        return ProviderInfo(
            name=self.name, kind=self.kind, capabilities=["text"],
            priority=self.priority, enabled=self.enabled, available=True,
        )


def test_dummy_satisfies_provider_protocol():
    assert isinstance(_Dummy(), Provider)


def test_errors_carry_capability():
    assert NoProviderAvailable("vision").capability == "vision"
    assert CapabilityUnavailable("text").capability == "text"
