"""Orchestrate one custodian run: survey -> fingerprint skip -> pick model -> brokered
dispatch -> write a markdown report. Read-only: writes only under CUSTODIAN_DIR."""
from __future__ import annotations
import datetime, json, os
from pathlib import Path
from config import KNIOX_HOME
import custodian_survey, custodian_model
import daemon as registry

_ALIGNMENT = KNIOX_HOME / "alignment" / "PROJECT-ALIGNMENT-REQUIREMENT.md"

_INSTRUCTION = ("You are the kniox custodian. Review the framework state below against the "
                "alignment contract. Report ONLY: misalignments, easy wins, bugs, and "
                "optimizations. Propose changes; do NOT apply them. Be concise and specific.")


def _custodian_dir() -> Path:
    return Path(os.environ.get("KNIOX_CUSTODIAN_DIR", KNIOX_HOME / "custodian"))


def _reports_dir() -> Path:
    return _custodian_dir() / "reports"


def _state_path() -> Path:
    return _custodian_dir() / "state.json"


def _alignment_text():
    try:
        return _ALIGNMENT.read_text()
    except OSError:
        return "(alignment contract unavailable)"


def build_prompt(survey: dict, alignment_text: str) -> str:
    digest = json.dumps(survey, indent=2, default=str)
    return (f"{_INSTRUCTION}\n\n## Alignment contract\n{alignment_text}\n\n"
            f"## Framework state (survey)\n{digest}\n")


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict):
    _custodian_dir().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2))


def _write_report(text: str) -> Path:
    reports = _reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    path = reports / f"custodian_{stamp}.md"
    path.write_text(text)
    (reports / "latest.md").write_text(text)
    return path


def run(force: bool = False) -> dict:
    survey = custodian_survey.survey()
    fp = custodian_survey.material_fingerprint(survey)
    if not force and _load_state().get("fingerprint") == fp:
        return {"skipped": True, "reason": "no change since last report"}
    model, reason = custodian_model.select_model()
    if not model:
        return {"skipped": True, "reason": reason}
    out = registry.dispatch("custodian", build_prompt(survey, _alignment_text()), model)
    if out.get("error"):
        return {"skipped": True, "reason": out["error"], "model": model}
    path = _write_report(out.get("response", ""))
    _save_state({"fingerprint": fp})
    return {"written": True, "path": str(path), "model": model}
