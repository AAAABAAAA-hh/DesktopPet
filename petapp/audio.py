"""Tiny WAV sound player.

QtMultimedia is not present in every PyQt6 installation, so Deskling uses
Windows' built-in winsound module.  All bundled clips are deliberately quiet;
users can replace them with their own recordings.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import CharacterConfig

log = logging.getLogger(__name__)

try:
    import winsound  # type: ignore
except Exception:  # pragma: no cover - non-Windows fallback
    winsound = None


class SoundPlayer:
    def __init__(self, sounds_dir: Path, enabled: bool = True) -> None:
        self.sounds_dir = Path(sounds_dir)
        self.enabled = enabled
        self._last_played: dict[str, float] = {}
        self._last_voice = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if not enabled:
            self.stop()

    def stop(self) -> None:
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def _play(self, path: Path, key: str, min_interval: float = 0.06) -> bool:
        if not self.enabled or winsound is None or not path.exists():
            return False
        now = time.monotonic()
        if now - self._last_played.get(key, 0.0) < min_interval:
            return False
        self._last_played[key] = now
        try:
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return True
        except Exception as exc:  # pragma: no cover - system dependent
            log.debug("sound failed (%s): %s", path.name, exc)
            return False

    def sfx(self, name: str, min_interval: float = 0.06) -> bool:
        """Play a shared effect, e.g. pop / pat / eat / rage."""
        stem = Path(name).stem
        return self._play(self.sounds_dir / f"{stem}.wav", f"sfx:{stem}", min_interval)

    def voice(self, character: "CharacterConfig", kind: str = "poke") -> bool:
        """Play one of the character's voice clips (or stay quiet)."""
        if not self.enabled:
            return False
        now = time.monotonic()
        if now - self._last_voice < 0.45:
            return False
        folder = character.folder / "voice"
        if not folder.exists():
            return False
        preferred: list[Path] = []
        if kind in {"angry", "rage"}:
            preferred.append(folder / "angry.wav")
        elif kind in {"happy", "pat", "eat"}:
            preferred.append(folder / "happy.wav")
        elif kind == "sleep":
            preferred.append(folder / "sleep.wav")
        else:
            preferred.extend(sorted(folder.glob("voice_*.wav")))
        preferred.extend(sorted(folder.glob("*.wav")))
        for path in preferred:
            if path.exists() and self._play(path, f"voice:{path}", 0.0):
                self._last_voice = now
                return True
        return False
