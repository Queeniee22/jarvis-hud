"""Run both suites: pytest for the backend, node --test for the frontend.

Two runtimes means two runners; this is the one command that covers the
whole project so neither half gets forgotten.

    .venv/Scripts/python run_tests.py     # Windows
    .venv/bin/python run_tests.py         # macOS
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def run(label: str, cmd: list[str]) -> int:
    print(f"\n=== {label} ===", flush=True)
    return subprocess.call(cmd, cwd=ROOT, shell=False)


def main() -> int:
    failed = []

    if run("backend (pytest)", [sys.executable, "-m", "pytest", "-q"]):
        failed.append("backend")

    # npm lives behind a .cmd shim on Windows; shell=True is needed there.
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    print("\n=== frontend (node --test) ===", flush=True)
    if subprocess.call([npm, "test", "--silent"], cwd=ROOT):
        failed.append("frontend")

    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nAll suites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
