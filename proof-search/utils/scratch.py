#!/usr/bin/env python3
"""Run a proof attempt on a temporary copy of its source file."""

import re
import shutil
import uuid
from pathlib import Path
from typing import Optional, Union

# Artifacts Coq leaves beside a .v file; they belong to the scratch copy.
_BUILD_SUFFIXES = (".vo", ".vok", ".vos", ".glob", ".aux")


def _module_safe(stem: str) -> str:
    """Turn a file stem into something Coq accepts as a module name."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    if not safe or not safe[0].isalpha():
        safe = f"v_{safe}"
    return safe


class ScratchProof:
    """A disposable copy of a .v file, for one proof attempt."""

    def __init__(self, source: Union[str, Path], logger=None):
        self.source = Path(source).resolve()
        self.logger = logger
        self.path = self.source.with_name(
            f"{_module_safe(self.source.stem)}_autorocq_{uuid.uuid4().hex[:12]}.v"
        )
        self._coqproject = self.source.parent / "_CoqProject"
        self._coqproject_backup: Optional[bytes] = None

    def open(self) -> Path:
        """Create the scratch copy and return its path."""
        shutil.copyfile(self.source, self.path)

        # CoqInterface regenerates _CoqProject from config on load, which would
        # otherwise leave the source tree modified too.
        if self._coqproject.exists():
            self._coqproject_backup = self._coqproject.read_bytes()

        self._log(f"📄 Proving on scratch copy: {self.path.name} (original untouched)")
        return self.path

    def save(self, dest_dir: Union[str, Path], name: Optional[str] = None) -> Optional[Path]:
        """Copy whatever the agent produced into dest_dir. Returns the saved path."""
        if not self.path.exists():
            self._log("⚠️ No scratch file to save - nothing was produced")
            return None

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / (name or self.source.name)
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = dest.with_name(f"{stem}.{counter}{suffix}")
            counter += 1

        shutil.copyfile(self.path, dest)
        self._log(f"💾 Saved resulting proof: {dest}")
        return dest

    def close(self) -> None:
        """Remove the scratch copy and undo the run's edits to the source tree."""
        litter = [self.path, self.path.with_name(f".{self.path.stem}.aux")]
        litter += [self.path.with_suffix(suffix) for suffix in _BUILD_SUFFIXES]

        for path in litter:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                self._log(f"⚠️ Could not remove {path.name}: {e}")

        if self._coqproject_backup is not None:
            try:
                if self._coqproject.read_bytes() != self._coqproject_backup:
                    self._coqproject.write_bytes(self._coqproject_backup)
                    self._log("♻️ Restored _CoqProject")
            except OSError as e:
                self._log(f"⚠️ Could not restore _CoqProject: {e}")
            self._coqproject_backup = None

    def __enter__(self) -> "ScratchProof":
        self.open()
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)
        else:
            print(message)
