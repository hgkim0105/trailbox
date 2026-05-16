"""Persisted Hub connection settings (QSettings — survives across runs)."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSettings

_ORG = "Trailbox"
_APP = "Trailbox"
_GROUP = "hub"


@dataclass
class HubSettings:
    url: str = ""        # e.g. "http://hub.local:8765"
    token: str = ""      # X-Trailbox-Token

    @property
    def configured(self) -> bool:
        return bool(self.url)


def load() -> HubSettings:
    s = QSettings(_ORG, _APP)
    s.beginGroup(_GROUP)
    try:
        return HubSettings(
            url=str(s.value("url", "") or "").strip(),
            token=str(s.value("token", "") or "").strip(),
        )
    finally:
        s.endGroup()


def save(settings: HubSettings) -> None:
    s = QSettings(_ORG, _APP)
    s.beginGroup(_GROUP)
    try:
        s.setValue("url", settings.url.strip())
        s.setValue("token", settings.token.strip())
    finally:
        s.endGroup()
    s.sync()
