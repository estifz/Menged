"""Text normalisation for place search, with Amharic (Ge'ez script) support.

Several Ge'ez letter families sound identical in modern Amharic and people
spell the same name with any of them, e.g. ሀ/ሐ/ኀ, ሰ/ሠ, አ/ዐ, ጸ/ፀ. We fold
each family to one form so "መድሃኔዓለም" and "መድኃኔአለም" match.
"""

import re
import unicodedata

# Each Ge'ez consonant has 7 vowel orders laid out consecutively in Unicode.
_FAMILY_FOLDS = {
    0x1210: 0x1200,  # ሐ -> ሀ
    0x1280: 0x1200,  # ኀ -> ሀ
    0x1220: 0x1230,  # ሠ -> ሰ
    0x12D0: 0x12A0,  # ዐ -> አ
    0x1340: 0x1338,  # ፀ -> ጸ
}

_FOLD_TABLE: dict[int, int] = {}
for src, dst in _FAMILY_FOLDS.items():
    for order in range(7):
        _FOLD_TABLE[src + order] = dst + order
# The 1st and 4th orders of ሀ (ሀ/ሃ) and of አ (አ/ኣ) are pronounced alike.
_FOLD_TABLE[0x1203] = 0x1200
_FOLD_TABLE[0x12A3] = 0x12A0
for _k, _v in list(_FOLD_TABLE.items()):
    if _v in (0x1203, 0x12A3):
        _FOLD_TABLE[_k] = _v - 3

_PUNCT = re.compile(r"[\s\-_.,;:!?'\"()/\\፡።፣፤፥፦]+")


def normalize(text: str) -> str:
    """Lower-case, fold Ge'ez variants, strip punctuation, collapse spaces."""
    text = unicodedata.normalize("NFC", text).lower().translate(_FOLD_TABLE)
    return _PUNCT.sub(" ", text).strip()


def is_amharic(text: str) -> bool:
    return any(0x1200 <= ord(ch) <= 0x139F for ch in text)
