"""Credentials from process env or mounted secret files, never from HTTP bodies/config DB."""

import os
from pathlib import Path

from app.errors import ProviderError

SECRET_VALUES = set()


def secret(name, required=False):
    value = os.getenv(name)
    path = os.getenv(name + "_FILE")
    if not value and path:
        try:
            source = Path(path)
            if source.stat().st_size > 16_384:
                raise OSError
            value = source.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            if required:
                raise ProviderError(f"Secretul {name}_FILE nu poate fi citit.") from None
            return None
    if value:
        SECRET_VALUES.add(value)
    elif required:
        raise ProviderError(
            f"{name} lipsește din mediul procesului sau din fișierul secret configurat."
        )
    return value or None
