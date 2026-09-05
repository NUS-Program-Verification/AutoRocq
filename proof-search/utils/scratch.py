#!/usr/bin/env python3
"""Give a proof attempt a private copy of the .v file to work on.

The agent proves in place: it strips the existing tactics from the file, and
coqpyt writes every accepted tactic straight back to disk. Pointed at a source
file, a run therefore destroys that file -- the original proof is gone and the
working tree is dirty. A single benchmark run rewrites every .v in
AutoRocq-bench this way.

ScratchProof hands the agent a throwaway copy instead. The copy lives beside
the original so the workspace still resolves exactly as before (same
_CoqProject, sibling modules and library paths), and the finished proof is
saved into the run's output directory, where it stays available for
independent re-checking instead of being overwritten by the next run.
"""

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

    def __init__(self, source: Union[str, Path], logger=None, workspace: Optional[Union[str, Path]] = None):
        self.source = Path(source).resolve()
        self.logger = logger
        self.path = self.source.with_name(
            f"{_module_safe(self.source.stem)}_autorocq_{uuid.uuid4().hex[:12]}.v"
        )
        self._coqproject = Path(workspace).resolve() / "_CoqProject" if workspace else self.source.parent / "_CoqProject"
        self._coqproject_backup: Optional[bytes] = None
        self._coqproject_existed = False

    def open(self) -> Path:
        """Create the scratch copy and return its path."""
        shutil.copyfile(self.source, self.path)

        # CoqInterface regenerates _CoqProject from config on load, which would
        # otherwise leave the source tree modified too.
        self._coqproject_existed = self._coqproject.exists()
        if self._coqproject_existed:
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
        counter = 1
        while dest.exists():
            dest = dest.with_name(f"{dest.stem}.{counter}{dest.suffix}")
            counter += 1

        shutil.copyfile(self.path, dest)
        self._log(f"💾 Saved resulting proof: {dest}")
        return dest

    def close(self) -> None:
        """Remove the scratch copy and undo the run's edits to the source tree."""
        litter = [self.path, self.path.with_suffix(".v.backup")]
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
        elif not self._coqproject_existed:
            try:
                self._coqproject.unlink()
                self._log("♻️ Removed generated _CoqProject")
            except FileNotFoundError:
                pass
            except OSError as e:
                self._log(f"⚠️ Could not remove generated _CoqProject: {e}")

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
