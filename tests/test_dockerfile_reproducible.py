"""Reproducibility guards for the production Dockerfile.

The 2026-09-26 outage investigation had to rule out base-image drift because
two builds of the same commit could differ: `FROM python:3.12-slim` floated to
whatever the tag pointed at on build day, and the runtime stage ran a floating
`apt-get install`. These tests keep the image reproducible: every image the
build pulls is pinned by digest, and the runtime (final) stage installs
nothing from apt. Digest bumps are deliberate edits, not side effects.
"""

from __future__ import annotations

import pathlib
import re

DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"


def _instructions() -> list[tuple[str, str]]:
    """(KEYWORD, args) per instruction, with line continuations joined."""
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        keyword, _, args = buf.partition(" ")
        out.append((keyword.upper(), args.strip()))
        buf = ""
    return out


def _stages() -> list[tuple[str, str | None, list[tuple[str, str]]]]:
    """(image, stage_name, instructions) per build stage."""
    stages: list[tuple[str, str | None, list[tuple[str, str]]]] = []
    for keyword, args in _instructions():
        if keyword == "FROM":
            tokens = [t for t in args.split() if not t.startswith("--")]
            name = tokens[2] if len(tokens) >= 3 and tokens[1].upper() == "AS" else None
            stages.append((tokens[0], name, []))
        elif stages:
            stages[-1][2].append((keyword, args))
    return stages


def test_every_from_is_pinned_by_digest():
    stages = _stages()
    assert stages, "no FROM found in Dockerfile"
    names = {name for _, name, _ in stages if name}
    unpinned = [image for image, _, _ in stages if image not in names and "@sha256:" not in image]
    assert not unpinned, f"FROM images not pinned by digest: {unpinned}"


def test_copy_from_images_are_pinned_by_digest():
    stages = _stages()
    names = {name for _, name, _ in stages if name}
    unpinned = []
    for _, _, instructions in stages:
        for keyword, args in instructions:
            m = re.search(r"--from=(\S+)", args) if keyword == "COPY" else None
            if m and m.group(1) not in names and "@sha256:" not in m.group(1):
                unpinned.append(m.group(1))
    assert not unpinned, f"COPY --from images not pinned by digest: {unpinned}"


def test_runtime_stage_installs_nothing_from_apt():
    _, _, runtime = _stages()[-1]
    apt_runs = [args for keyword, args in runtime if keyword == "RUN" and re.search(r"\bapt(-get)?\b", args)]
    assert not apt_runs, f"runtime stage runs apt: {apt_runs}"
