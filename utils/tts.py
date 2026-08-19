"""Text-to-speech using the Windows built-in SAPI5 voices.

No third-party dependency — we shell out to PowerShell's
``System.Speech.Synthesis.SpeechSynthesizer``. The script is passed as a
base64-encoded UTF-16LE command so arbitrary text (including Chinese and
newlines) is embedded safely without shell-escaping headaches.
"""

import base64
import re
import subprocess

# Tracks the currently running speech process so we can stop it on demand.
_proc = None

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# Matches runs of Latin letters (with optional internal apostrophes) — i.e.
# "English words" in otherwise mixed (e.g. translated) text.
_ENGLISH = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

# SAPI5 Rate range is roughly -10 (slowest) .. 10 (fastest); 0 is default.
# We read aloud slowly so the user can follow the pronunciation.
DEFAULT_RATE = -3


def has_cjk(text: str) -> bool:
    """Return True if *text* contains CJK characters."""
    return bool(_CJK.search(text))


def extract_english_words(text: str) -> str:
    """Return only the English word tokens from *text*, space-joined.

    Useful when the translation result is mostly Chinese but the user wants
    to hear how the English terms/source words are pronounced.
    """
    return " ".join(_ENGLISH.findall(text))


def extract_english_sentences(text: str) -> str:
    """Return the English example sentences found in *text*, space-joined.

    Splits on sentence boundaries (English + Chinese punctuation and newlines)
    and keeps only fragments that contain at least 3 English words — i.e. real
    example sentences rather than Chinese lines that merely borrow a word.
    """
    fragments = re.split(r"(?<=[.!?。！？])\s*|\n+", text)
    kept = []
    for frag in fragments:
        frag = frag.strip()
        if not frag:
            continue
        english_words = _ENGLISH.findall(frag)
        if len(english_words) >= 3:
            kept.append(frag)
    return " ".join(kept)


def is_speaking() -> bool:
    """Return True while a speech process is still running."""
    return _proc is not None and _proc.poll() is None


def stop() -> None:
    """Stop any ongoing speech."""
    global _proc
    if _proc is not None:
        try:
            if _proc.poll() is None:
                _proc.terminate()
        except Exception:
            pass
    _proc = None


def speak(text: str, rate: int = DEFAULT_RATE) -> bool:
    """Speak *text* asynchronously using the system (English) voice.

    The caller is expected to filter the text to English words (see
    :func:`extract_english_words`) — the read-aloud feature only pronounces
    English, at a deliberately slow rate. Returns True if speech started.
    """
    global _proc
    if not text or not text.strip():
        return False

    text = text.strip()

    # Here-string ('@ ... '@) embeds the text verbatim, no escaping needed.
    script = (
        "Add-Type -AssemblyName System.Speech\n"
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f"$synth.Rate = {rate}\n"
        "$synth.Speak(@'\n"
        f"{text}\n"
        "'@)\n"
    )

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        _proc = subprocess.Popen(
            ["powershell", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        _proc = None
        return False
    return True
