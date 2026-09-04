"""Shared UTF-8 length helper that fails closed on unpaired surrogates."""


def utf8_length(value):
    """Byte length of ``value`` in UTF-8, or +inf if it cannot be encoded.

    Several validators across this package bound text by UTF-8 byte
    length. A Python ``str`` can carry an unpaired UTF-16 surrogate (for
    example from a JSON ``\\ud800``-style escape) that fails
    ``str.encode("utf-8")`` with a raw ``UnicodeEncodeError`` -- not any
    of this package's own domain error types. Treating such a value as
    infinitely long makes every existing "exceeds N bytes" bound check
    reject it the same way an oversized value would, without each call
    site needing its own try/except.
    """
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return float("inf")
