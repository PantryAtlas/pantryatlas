from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def test_avahi_service_advertises_pantryatlas():
    path = _REPO / "ops" / "avahi" / "pantryatlas.service"
    assert path.exists(), "avahi service file missing"
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    assert root.tag == "service-group"
    svc = root.find("service")
    assert svc is not None
    assert svc.findtext("type") == "_pantryatlas._tcp"
    assert svc.findtext("port") == "8090"
    txts = [t.text for t in svc.findall("txt-record")]
    assert "role=hub" in txts


def test_install_sh_installs_avahi_service():
    install = (_REPO / "ops" / "systemd" / "install.sh").read_text(encoding="utf-8")
    assert "avahi/pantryatlas.service" in install
    assert "/etc/avahi/services" in install
