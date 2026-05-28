from pantryatlas.ops import image_build


def test_units_to_enable_is_lean():
    units = image_build.UNITS_TO_ENABLE
    assert "pantryatlas-navigator" in units
    assert "pantryatlas-embeddings" in units
    assert "pantryatlas-mem-monitor" in units
    # lean image must NOT enable the LLM service
    assert not any("gemma" in u for u in units)


def test_nftables_ruleset_redirects_80_to_8090():
    rs = image_build.nftables_ruleset()
    assert "dport 80" in rs
    assert "8090" in rs
    # custom ports honored
    rs2 = image_build.nftables_ruleset(dport=8080, to_port=9000)
    assert "dport 8080" in rs2
    assert "9000" in rs2


def test_build_image_manifest_keys_and_types():
    m = image_build.build_image_manifest(
        image_version="v0.2.0",
        base_image="raspios-lite-arm64-2026-05-01",
        base_image_sha256="b" * 64,
        recipes_db_sha256="d" * 64,
        bge_m3_sha256="e" * 64,
        pantryatlas_commit="c" * 40,
        sha256="a" * 64,
        bytes_=123,
        built_at="2026-05-28T00:00:00Z",
    )
    assert m["image_version"] == "v0.2.0"
    assert m["base_image"] == "raspios-lite-arm64-2026-05-01"
    assert m["base_image_sha256"] == "b" * 64
    assert m["recipes_db_sha256"] == "d" * 64
    assert m["bge_m3_sha256"] == "e" * 64
    assert m["pantryatlas_commit"] == "c" * 40
    assert m["url"].endswith("/pantryatlas-v0.2.0.img.xz")
    assert m["sha256"] == "a" * 64
    assert isinstance(m["bytes"], int)
