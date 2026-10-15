"""Read-only planning checks using the standard library; never application QA."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/design-v2"
BASE = "1c4c23f092fde34ce527ebb27309f57a8c5ec5bb"


def read(path: Path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid)


def main() -> int:
    checks = []

    def require(ok, name):
        if not ok:
            raise ValueError(name)
        checks.append(name)

    reqs = read(DESIGN / "planning/requirements.json")["requirements"]
    cases = read(DESIGN / "planning/acceptance-tests.json")["tests"]
    tasks = read(DESIGN / "planning/tasks.json")["tasks"]
    rules = read(DESIGN / "contracts/behavior-matrix.json")["rules"]
    spec = (DESIGN / "IMPLEMENTATION_SPEC.md").read_text(encoding="utf-8")
    rids, tids, wids = ({x["id"] for x in xs} for xs in (reqs, cases, tasks))
    require((len(reqs), len(cases), len(tasks), len(rules)) == (78, 85, 18, 31),
            "Catalog counts are 78 requirements, 85 cases, 18 packets, 31 events")
    require((len(rids), len(tids), len(wids)) == (78, 85, 18), "Unique catalog IDs")
    defined = re.findall(r"^### (R-[A-Z0-9-]+) \| .+ \| (?:CORE|CONDITIONAL)$", spec, re.MULTILINE)
    require(len(defined) == len(set(defined)) and set(defined) == rids,
            "Specification headings and requirements agree")
    for req in reqs:
        require(bool(req["tests"]) and set(req["tests"]) <= tids
                and bool(req["tasks"]) and set(req["tasks"]) <= wids,
                f"{req['id']} references resolve")
        require(set(req["tests"]) == {x["id"] for x in cases if req["id"] in x["requirements"]},
                f"{req['id']} bidirectional case mapping")
    require(all(set(x["requirements"]) <= rids and x["given"] and x["steps"]
                and x["expected"] for x in cases), "All cases have valid IDs and independent oracle fields")
    require(all(x["evidence_status"] == "NOT_RUN" for x in cases), "All 85 application cases remain NOT_RUN")
    require(all(x["status"] == "NOT_STARTED" for x in tasks), "Source packets make no completion claims")
    deps = {x["id"]: x["depends_on"] for x in tasks}
    seen, active = set(), set()

    def visit(key):
        if key in active:
            raise ValueError(f"Dependency cycle: {key}")
        if key in seen:
            return
        active.add(key)
        for dep in deps[key]:
            visit(dep)
        active.remove(key)
        seen.add(key)

    for task in tasks:
        require(set(task["depends_on"]) <= wids and set(task["requirements"]) <= rids
                and set(task["acceptance_tests"]) <= tids, f"{task['id']} references resolve")
        visit(task["id"])
    require(len(seen) == 18, "Task graph is acyclic and complete")
    require(len({x["event"] for x in rules}) == 31, "Unique behavior events")
    files = read(DESIGN / "verification/SHA256SUMS.json")["files"]
    for name, digest in files.items():
        path = (DESIGN / name).resolve()
        require(path.is_relative_to(DESIGN.resolve()) and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                f"Adopted checksum: {name}")
    mapping = read(ROOT / "docs/planning/execution-map.json")["packets"]
    require({x["packet"] for x in mapping} == wids, "Every packet has a repository execution map")
    for row in mapping:
        original = next(t for t in tasks if t["id"] == row["packet"])
        require(row["depends_on"] == original["depends_on"]
                and row["requirements"] == original["requirements"]
                and row["acceptance_tests"] == original["acceptance_tests"],
                f"{row['packet']} overlay preserves normative references")
    auth = read(ROOT / "docs/planning/authorization.json")
    require(auth["github_owner"] == "Brak23" and auth["target_repo_name"] == "mithril-voices"
            and auth["first_push_approved"] and auth["application_implementation_approved"]
            and not auth["paid_actions_approved"] and not auth["run_workflows_approved"]
            and not auth["merge_policy_approved"] and not auth["publish_release_approved"],
            "Current authorization retains fork and publication boundaries")
    if auth["scope"] == "WP00_LOCAL_BASELINE_AND_ONE_PORTABLE_WP01_COMPONENT":
        changed = subprocess.check_output(["git", "diff", "--name-only", BASE], cwd=ROOT, text=True).splitlines()
        new = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
        require(all(p.startswith(("docs/", "tools/", "tests/v2/")) or p in {"AGENTS.md", "START_HERE.md"} for p in changed + new),
                "Original bounded adoption diff contains only authorized paths")
    else:
        require(auth["scope"] == "BOUNDED_WINDOWS_IMPLEMENTATION_WITH_GAME_DEFERRED"
                and auth["windows_pc_access_approved"] and auth["game_launch_or_interaction_deferred"],
                "Current Windows implementation scope is recorded")
    print(json.dumps({"scope": "PLANNING_DATA_ONLY_NOT_APPLICATION_QA", "status": "PASSED",
                      "code_base_sha": BASE, "spec_version": "2.0",
                      "spec_sha256": hashlib.sha256((DESIGN / "IMPLEMENTATION_SPEC.md").read_bytes()).hexdigest(),
                      "passed_planning_checks": len(checks), "checks": checks,
                      "requirements": 78, "acceptance_cases": 85, "behavior_events": 31, "packets": 18,
                      "application_tests_executed": 0, "application_cases_status": "ALL_NOT_RUN",
                      "full_schema_validation": "NOT_PERFORMED_BY_THIS_CATALOG_CHECKER_SEE_CURRENT_REPORTS",
                      "note": "Read-only catalog/hash/reference checks; not the source author's 625 checks or any G0-G4 gate."}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"FAILED planning check: {exc}", file=sys.stderr)
        sys.exit(1)
