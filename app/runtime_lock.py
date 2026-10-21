"""One application or offline maintenance process per data directory, on Windows/Linux."""

import os
from pathlib import Path


class RuntimeLock:
    def __init__(self, data_dir):
        self.path = Path(data_dir).resolve() / ".runtime.lock"
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Runtime lock must not be a symbolic link")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.handle = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt

                if not self.path.stat().st_size:
                    self.handle.write(b"0")
                self.handle.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise ValueError(
                "Close MemeScope before offline maintenance; data directory is in use."
            ) from None
        return self

    def __exit__(self, *_):
        if self.handle:
            # Closing releases the OS lock, including after crashes. Do not unlink
            # the file: another process could still be waiting on its inode.
            self.handle.close()
            self.handle = None
