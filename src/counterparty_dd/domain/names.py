import re
import unicodedata
from difflib import SequenceMatcher

_CYR_TO_LAT = {
    "А": "A",
    "Б": "B",
    "В": "V",
    "Г": "G",
    "Д": "D",
    "Е": "E",
    "Ё": "E",
    "Ж": "ZH",
    "З": "Z",
    "И": "I",
    "Й": "I",
    "К": "K",
    "Л": "L",
    "М": "M",
    "Н": "N",
    "О": "O",
    "П": "P",
    "Р": "R",
    "С": "S",
    "Т": "T",
    "У": "U",
    "Ф": "F",
    "Х": "KH",
    "Ц": "TS",
    "Ч": "CH",
    "Ш": "SH",
    "Щ": "SHCH",
    "Ъ": "",
    "Ы": "Y",
    "Ь": "",
    "Э": "E",
    "Ю": "IU",
    "Я": "IA",
}
_LEGAL_FORMS = frozenset(
    {
        "OOO",
        "AO",
        "PAO",
        "ZAO",
        "OAO",
        "NAO",
        "IP",
        "ANO",
        "NKO",
        "FGUP",
        "GUP",
        "MUP",
        "TOO",
        "LLC",
        "LTD",
        "INC",
        "CORP",
        "GMBH",
        "AG",
        "SA",
        "NV",
        "BV",
        "PLC",
        "LIMITED",
        "COMPANY",
        "CO",
    }
)
_NON_ALNUM = re.compile(r"[^0-9A-Z]+")


def normalize(name: str) -> str:
    upper = unicodedata.normalize("NFKD", name.upper())
    transliterated = "".join(_CYR_TO_LAT.get(c, c) for c in upper if unicodedata.category(c) != "Mn")
    tokens = [t for t in _NON_ALNUM.split(transliterated) if t and t not in _LEGAL_FORMS]
    return " ".join(tokens)


def tokens(name: str) -> frozenset[str]:
    return frozenset(normalize(name).split())


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    left, right = " ".join(sorted(ta)), " ".join(sorted(tb))
    ratio = max(SequenceMatcher(None, left, right).ratio(), SequenceMatcher(None, right, left).ratio())
    return round(max(jaccard, ratio), 4)
