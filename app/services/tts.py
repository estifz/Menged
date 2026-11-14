"""Text-to-speech for bot voice notes, using gTTS (free, no key).

Audio is cached on disk by (language, text), so common phrases are generated
once. When ffmpeg is installed we convert to OGG/Opus (Telegram's native voice
format); otherwise we send the MP3, which Telegram also accepts.
"""

import asyncio
import hashlib
import logging
import shutil
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)

_lock = asyncio.Semaphore(2)  # gTTS calls Google Translate; keep it gentle
_supported: set[str] | None = None


def supported_languages() -> set[str]:
    global _supported
    if _supported is None:
        try:
            from gtts.lang import tts_langs

            _supported = set(tts_langs().keys())
        except Exception:  # pragma: no cover
            _supported = {"en"}
    return _supported


def _path_for(text: str, lang: str, ext: str) -> Path:
    digest = hashlib.sha1(f"{lang}:{text}".encode()).hexdigest()[:20]
    return Path(get_settings().tts_cache_dir) / f"{lang}-{digest}.{ext}"


def _generate(text: str, lang: str, mp3: Path) -> None:
    from gtts import gTTS

    mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp = mp3.with_suffix(".tmp")
    gTTS(text=text, lang=lang).save(str(tmp))
    tmp.replace(mp3)


async def _to_ogg(mp3: Path, ogg: Path) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-c:a", "libopus", "-b:a", "32k", str(ogg),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        log.warning("ffmpeg failed: %s", err.decode(errors="ignore")[:200])
        return False
    return True


async def synthesize(text: str, lang: str) -> Path | None:
    """Returns a path to an audio file, or None if voice is unavailable."""
    if not get_settings().tts_enabled:
        return None
    if lang not in supported_languages():
        return None  # text only; never read Amharic text with an English voice
    ogg = _path_for(text, lang, "ogg")
    if ogg.exists():
        return ogg
    mp3 = _path_for(text, lang, "mp3")
    try:
        if not mp3.exists():
            async with _lock:
                await asyncio.to_thread(_generate, text, lang, mp3)
    except Exception as e:
        log.warning("gTTS failed (%s): %s", lang, e)
        return None
    if shutil.which("ffmpeg") and await _to_ogg(mp3, ogg):
        return ogg
    return mp3
