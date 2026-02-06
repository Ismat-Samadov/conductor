"""Azerbaijani text normalization and transliteration for stop name matching."""

# Latin→Azerbaijani character map (user may type without special chars)
_TRANSLIT_MAP = {
    "sh": "ş",
    "ch": "ç",
    "gh": "ğ",
    "oe": "ö",
    "ue": "ü",
}

# Single-char fallback (applied after multi-char)
_CHAR_MAP = {
    "ə": "e",
    "ş": "s",
    "ç": "c",
    "ö": "o",
    "ü": "u",
    "ğ": "g",
    "ı": "i",
}

_REVERSE_CHAR_MAP = {v: k for k, v in _CHAR_MAP.items()}


def normalize(text: str) -> str:
    """Lowercase and strip whitespace. Preserves Azerbaijani characters."""
    return text.strip().lower()


def to_ascii(text: str) -> str:
    """Convert Azerbaijani characters to ASCII equivalents for comparison."""
    result = normalize(text)
    for az_char, ascii_char in _CHAR_MAP.items():
        result = result.replace(az_char, ascii_char)
    return result


def expand_to_azerbaijani(text: str) -> str:
    """
    Convert ASCII input to possible Azerbaijani form.
    e.g., 'genclik' → 'gənclik', 'koroglu' → 'koroğlu'
    """
    result = normalize(text)
    # First apply multi-char substitutions
    for ascii_seq, az_char in _TRANSLIT_MAP.items():
        result = result.replace(ascii_seq, az_char)
    # Then single-char (only where it makes sense — e→ə is too aggressive alone)
    return result


def generate_variants(text: str) -> list[str]:
    """
    Generate multiple search variants from user input.
    Returns list of normalized strings to try against stop names.
    """
    text = normalize(text)
    variants = [text]

    # ASCII version
    ascii_ver = to_ascii(text)
    if ascii_ver != text:
        variants.append(ascii_ver)

    # Azerbaijani-expanded version
    az_ver = expand_to_azerbaijani(text)
    if az_ver != text:
        variants.append(az_ver)

    # Try replacing each 'e' with 'ə' individually
    if "e" in text:
        variants.append(text.replace("e", "ə"))

    # Try replacing 'g' with 'ğ'
    if "g" in text:
        variants.append(text.replace("g", "ğ"))

    # Try replacing 'i' with 'ı'
    if "i" in text:
        variants.append(text.replace("i", "ı"))

    return list(dict.fromkeys(variants))  # dedupe, preserve order
