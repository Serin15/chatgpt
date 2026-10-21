"""Lossless cold JSON payloads in SQLite; row IDs and indexes stay in place.

Only snapshots and opportunity observations are eligible. Policies, signals,
decisions and trade results are never rewritten by the archiver. SQL JSON1
expressions must call archive_text() before inspecting an eligible column.
"""

import hashlib
import sqlite3
import struct
import zlib

MAGIC = b"\x00MEMESCOPE-ARCHIVE\x01"
MAX_BYTES = 16 * 1024 * 1024
HEADER = len(MAGIC) + 8 + 32


def decode(value):
    if not isinstance(value, bytes):
        return value
    if not value.startswith(MAGIC):
        return value
    if len(value) < HEADER:
        raise ValueError("Truncated archived payload")
    size = struct.unpack(">Q", value[len(MAGIC) : len(MAGIC) + 8])[0]
    if size > MAX_BYTES:
        raise ValueError("Archived payload exceeds the supported limit")
    stream = zlib.decompressobj()
    raw = stream.decompress(value[HEADER:], size + 1)
    # Never allocate an unbounded decompression buffer or accept trailing streams.
    if len(raw) != size or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError("Invalid archived payload size or stream")
    if hashlib.sha256(raw).digest() != value[len(MAGIC) + 8 : HEADER]:
        raise ValueError("Archived payload checksum mismatch")
    return raw.decode("utf-8", errors="strict")


def encode(value):
    if not isinstance(value, str):
        return value
    raw = value.encode("utf-8")
    if len(raw) > MAX_BYTES:
        return value
    packed = MAGIC + struct.pack(">Q", len(raw)) + hashlib.sha256(raw).digest()
    packed += zlib.compress(raw, level=6)
    # Small payloads remain plain text. No JSON normalization or rounding.
    if len(packed) >= len(raw):
        return value
    if decode(packed) != value:
        raise ValueError("Archive round-trip verification failed")
    return packed


def row_factory(cursor, row):
    return sqlite3.Row(cursor, tuple(decode(value) for value in row))


def configure(db):
    db.row_factory = row_factory
    # JSON1 often reads several paths from the same row. A one-value cache avoids
    # decompressing it repeatedly; memory stays bounded by MAX_BYTES per connection.
    previous = [None, None]

    def sql_decode(value):
        if not isinstance(value, bytes):
            return value
        if value != previous[0]:
            previous[:] = [value, decode(value)]
        return previous[1]

    db.create_function("archive_text", 1, sql_decode, deterministic=True)
