"""PULSE local crypto research and manual paper trading."""

from hashlib import sha256
from pathlib import Path

__version__ = "0.8.0"


def instance_id(data_dir):
    """Identify a data directory without exposing its absolute path in the API."""
    return sha256(str(Path(data_dir).resolve()).encode()).hexdigest()[:24]
