"""The single Job descriptor every caller hands the broker."""
from __future__ import annotations
from dataclasses import dataclass, field
import placement as _placement


def _mem_to_gb(v: str | None) -> float | None:
    if not v:
        return None
    v = v.strip().upper().rstrip("B")
    try:
        if v.endswith("G"):
            return float(v[:-1])
        if v.endswith("M"):
            return round(float(v[:-1]) / 1024, 3)
        return float(v)
    except ValueError:
        return None


@dataclass
class Job:
    task: str
    command: list[str] | None = None
    env: dict = field(default_factory=dict)
    needs_gpu: bool = False
    est_mem_gb: float | None = None
    est_vram_gb: float | None = None
    local_paths: list = field(default_factory=list)
    interactive: bool = False
    schedule: str | None = None
    placement: str | None = None   # explicit override or parsed header (non-auto)
    prompt: str | None = None      # for backend/LLM tasks
    source: str | None = None      # script text, embedded for self-contained cluster runs

    @classmethod
    def from_script(cls, path: str, task: str | None = None) -> "Job":
        with open(path) as f:
            text = f.read()
        parsed = _placement.parse_placement(text)
        placement_val = None
        mem = None
        if parsed and parsed["placement"] != "auto":
            placement_val = parsed["placement"]
        if parsed:
            mem = _mem_to_gb(parsed["hints"].get("mem"))
            task = task or parsed["hints"].get("task")
        return cls(task=task or "script", command=["uv", "run", path],
                   source=text, placement=placement_val, est_mem_gb=mem)
