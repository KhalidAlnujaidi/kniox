# Ensures sqlite-backed modules use a throwaway DB per test session.
import os, tempfile, pathlib
os.environ.setdefault("KNIOX_STATE_DIR", tempfile.mkdtemp(prefix="kniox-test-"))
pathlib.Path(os.environ["KNIOX_STATE_DIR"]).mkdir(parents=True, exist_ok=True)
