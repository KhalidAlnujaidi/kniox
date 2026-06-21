"""Parse the kniox placement pragma from a script header.

Convention: before the imports, a single comment declares where a job runs:
    # kniox: placement=<enigma-gpu|enigma-local|cluster|auto> [key=value ...]
This is the scheduler's fast path — one cheap read instead of inference.
"""
from __future__ import annotations
import re

VALID_PLACEMENTS = {"enigma-gpu", "enigma-local", "cluster", "auto"}
_HEADER = re.compile(r"#\s*kniox:\s*placement=(?P<p>[\w-]+)(?P<rest>.*)$")


def parse_placement(text: str) -> dict | None:
    for line in text.splitlines()[:20]:
        m = _HEADER.match(line.strip())
        if not m:
            continue
        p = m.group("p")
        if p not in VALID_PLACEMENTS:
            return None
        hints = dict(kv.split("=", 1) for kv in m.group("rest").split() if "=" in kv)
        return {"placement": p, "hints": hints}
    return None
