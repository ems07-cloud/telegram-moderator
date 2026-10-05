"""Нормализация текста против обхода фильтров: «з@работок», «kазино» с латинской k и т. п.

В оригинале это было помечено как TODO. Проверяем исходный текст и два варианта: с латинскими
двойниками, заменёнными на кириллицу, и наоборот — так ловятся обе стороны подмены.
"""
import unicodedata

_LAT_TO_CYR = str.maketrans({
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "m": "м",
    "t": "т", "h": "н", "b": "в", "3": "з", "0": "о", "@": "а", "$": "s", "6": "б",
})
_CYR_TO_LAT = str.maketrans({
    "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y", "к": "k", "м": "m",
    "т": "t", "н": "h", "в": "b", "0": "o", "@": "a", "$": "s",
})


def variants(text: str) -> list[str]:
    """Исходный текст и его «очищенные» варианты для поиска шаблонов."""
    if not text:
        return []
    base = unicodedata.normalize("NFKC", text).casefold()
    base = "".join(ch for ch in base if unicodedata.category(ch) != "Cf")   # невидимые символы-разделители
    return list(dict.fromkeys([text, base, base.translate(_LAT_TO_CYR), base.translate(_CYR_TO_LAT)]))
