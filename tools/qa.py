"""Bounded WP-01 contract-data lane. Other product suites remain BLOCKED."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ["tests/v2/test_contract_validation.py", "tests/v2/test_qa_contract_lane.py"]


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    return {"collected": len(cases), "failed": sum(c.find("failure") is not None or c.find("error") is not None for c in cases),
            "skipped": sum(c.find("skipped") is not None for c in cases)}


def passed(exit_code: int, counts: dict[str, int]) -> bool:
    return exit_code == 0 and counts["collected"] > 0 and counts["failed"] == 0 and counts["skipped"] == 0


def run_contract(report_path: Path | None) -> tuple[dict[str, Any], int]:
    for name in INVENTORY:
        if not (ROOT / name).is_file():
            raise ValueError("Missing required contract test inventory")
    with tempfile.TemporaryDirectory(prefix="mithril-contract-") as temp:
        junit = Path(temp) / "contract.xml"
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        command = [sys.executable, "-m", "pytest", *INVENTORY, "--confcutdir=tests/v2",
                   "-c", os.devnull, "--rootdir", str(ROOT), "-q", f"--junitxml={junit}"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False)
        counts = junit_counts(junit) if junit.exists() else {"collected": 0, "failed": 0, "skipped": 0}
        ok = passed(result.returncode, counts)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
        inputs = [*INVENTORY, "tools/qa.py", "tools/validate_contracts.py",
                  "docs/design-v2/contracts/defaults.json", "docs/design-v2/contracts/defaults.schema.json",
                  "docs/design-v2/contracts/ipc.schema.json", "docs/design-v2/contracts/ipc.examples.json"]
        report = {"scope": "WP01_CONTRACT_DATA_SLICE_NOT_COMPLETE_APPLICATION_CONTRACT_SUITE",
                  "status": "PASSED" if ok else "FAILED", "code_sha": sha, "dirty_tree": dirty,
                  "command": "python tools/qa.py --suite contract", "pytest_exit_code": result.returncode,
                  "exit_code": 0 if ok else 1, "environment": {"platform": platform.system(), "python": platform.python_version()},
                  "spec_version": "2.0", "spec_sha256": hashlib.sha256((ROOT / "docs/design-v2/IMPLEMENTATION_SPEC.md").read_bytes()).hexdigest(),
                  "inventory": INVENTORY, **counts, "passed": counts["collected"] - counts["failed"] - counts["skipped"],
                  "input_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs},
                  "application_runtime_acceptance_status": "NOT_RUN", "fixture_provenance": "ORIGINAL_SYNTHETIC_CONTRACT_NEGATIVES",
                  "limitations": ["Syntax validation is not lifecycle/authorization validation", "This lane does not qualify the Windows game, audio, capture or model runtime", "WP-01 and G1 remain incomplete"]}
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            if junit.exists():
                raw = report_path.with_suffix(".xml")
                raw.write_text(junit.read_text().replace(str(ROOT), "REPO_ROOT"), encoding="utf-8")
                report["raw_reports"] = [raw.name]
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not ok:
            print((result.stdout + result.stderr).replace(str(ROOT), "<REPO>"), file=sys.stderr)
        return report, 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["quick", "contract", "replay", "windows", "gpu", "package", "release"])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.suite != "contract":
        print(json.dumps({"status": "BLOCKED", "suite": args.suite,
                          "reason": "Not implemented or qualified in this first bounded WP-01 slice"}))
        return 2
    try:
        report, code = run_contract(args.report)
        print(json.dumps(report, indent=2))
        return code
    except (OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
