import re

_DIGITS = re.compile(r"\d+")
_INN10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _digits(value: str, *lengths: int) -> list[int] | None:
    if not _DIGITS.fullmatch(value) or len(value) not in lengths:
        return None
    return [int(c) for c in value]


def _control(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    d = _digits(value, 10, 12)
    if d is None:
        return False
    if len(d) == 10:
        return _control(d, _INN10) == d[9]
    return _control(d, _INN11) == d[10] and _control(d, _INN12) == d[11]


def is_valid_ogrn(value: str) -> bool:
    if _digits(value, 13) is None:
        return False
    return int(value[:12]) % 11 % 10 == int(value[12])


def is_valid_ogrnip(value: str) -> bool:
    if _digits(value, 15) is None:
        return False
    return int(value[:14]) % 13 % 10 == int(value[14])


def complete_inn(prefix: str) -> str:
    d = [int(c) for c in prefix]
    if len(d) == 9:
        return prefix + str(_control(d, _INN10))
    if len(d) == 10:
        d.append(_control(d, _INN11))
        d.append(_control(d, _INN12))
        return "".join(map(str, d))
    raise ValueError("Префикс ИНН должен содержать 9 или 10 цифр")


def complete_ogrn(prefix: str) -> str:
    if len(prefix) == 12:
        return prefix + str(int(prefix) % 11 % 10)
    if len(prefix) == 14:
        return prefix + str(int(prefix) % 13 % 10)
    raise ValueError("Префикс ОГРН/ОГРНИП должен содержать 12 или 14 цифр")
