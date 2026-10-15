#!/usr/bin/env python3
"""Validate the requirements handoff only. Does not test or install the application."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'verification' / 'handoff-validation.json'
errors: list[str] = []
checks: list[str] = []

def check(ok: bool, description: str) -> None:
    (checks if ok else errors).append(description)

def read_json(path: str):
    def invalid(value: str):
        raise ValueError(f'Nonfinite JSON constant in {path}: {value}')
    return json.loads((ROOT / path).read_text(encoding='utf-8'), parse_constant=invalid)

def main() -> int:
    try:
        import jsonschema
    except ImportError:
        print('BLOCKED: jsonschema is required for package schema checks. No dependencies were installed.')
        return 2
    spec = (ROOT / 'IMPLEMENTATION_SPEC.md').read_text(encoding='utf-8')
    requirements = read_json('planning/requirements.json')['requirements']
    tests = read_json('planning/acceptance-tests.json')['tests']
    tasks = read_json('planning/tasks.json')['tasks']
    sources = read_json('docs/sources.json')['sources']
    policy = read_json('contracts/behavior-matrix.json')['rules']
    rid = {x['id'] for x in requirements}; tid = {x['id'] for x in tests}; wid = {x['id'] for x in tasks}
    defined = re.findall(r'^### (R-[A-Z0-9-]+) \| .+ \| (?:CORE|CONDITIONAL)$', spec, re.M)
    check(len(defined) == len(set(defined)), 'No duplicate requirement headings')
    check(rid == set(defined), 'Requirement index matches all specification headings')
    check(len(tid) == len(tests) and len(wid) == len(tasks), 'Unique test and task IDs')
    for req in requirements:
        check(bool(req['tests']) and set(req['tests']) <= tid, f"{req['id']} has valid test coverage")
        check(bool(req['tasks']) and set(req['tasks']) <= wid, f"{req['id']} has task ownership")
        actual = {x['id'] for x in tests if req['id'] in x['requirements']}
        check(actual == set(req['tests']), f"{req['id']} bidirectional test traceability")
    for test in tests:
        check(set(test['requirements']) <= rid, f"{test['id']} uses real requirement IDs")
        check(bool(test['given']) and bool(test['steps']) and bool(test['expected']), f"{test['id']} has preconditions, actions and oracle")
        check(test['evidence_status'] == 'NOT_RUN', f"{test['id']} does not claim execution")
    for task in tasks:
        check(set(task['depends_on']) <= wid, f"{task['id']} prerequisites resolve")
        check(set(task['requirements']) <= rid, f"{task['id']} requirement references resolve")
        check(set(task['acceptance_tests']) <= tid, f"{task['id']} test references resolve")
        check(task['status'] == 'NOT_STARTED', f"{task['id']} does not claim implementation")
    deps = {t['id']: t['depends_on'] for t in tasks}
    seen: set[str] = set(); active: set[str] = set()
    def visit(n: str) -> None:
        if n in active: raise ValueError(f'Task dependency cycle at {n}')
        if n in seen: return
        active.add(n)
        for dep in deps[n]: visit(dep)
        active.remove(n); seen.add(n)
    try:
        for n in deps: visit(n)
        check(True, 'Task graph is acyclic')
    except ValueError as exc:
        check(False, str(exc))
    check(set(re.findall(r'\bAT-\d{3}\b', spec)) <= tid, 'All specification acceptance IDs resolve')
    check(set(re.findall(r'\bWP-\d{2}\b', spec)) <= wid, 'All specification packet IDs resolve')
    check(len({x['event'] for x in policy}) == len(policy), 'Unique policy event definitions')
    check(bool(policy) and all(x['ordered_effects'] and x['must_not'] for x in policy), 'Policy events have actions and prohibitions')
    source_ids = {x['id'] for x in sources}
    used_sources = set(re.findall(r'\[(S\d{2})\]', spec))
    check(used_sources <= source_ids, 'Named source IDs resolve')
    check('\u2014' not in spec, 'No em dashes in specification')
    check('1c4c23f092fde34ce527ebb27309f57a8c5ec5bb' in spec, 'Full pinned upstream SHA present')
    for name in ['ipc.schema.json', 'defaults.schema.json']:
        jsonschema.Draft202012Validator.check_schema(read_json('contracts/' + name))
        check(True, f'{name} is a valid Draft 2020-12 schema')
    dv = jsonschema.Draft202012Validator(read_json('contracts/defaults.schema.json'))
    defaults = read_json('contracts/defaults.json')
    dv.validate(defaults); check(True, 'Initial defaults validate')
    iv = jsonschema.Draft202012Validator(read_json('contracts/ipc.schema.json'))
    examples = read_json('contracts/ipc.examples.json')['examples']
    for i, example in enumerate(examples):
        iv.validate(example); check(True, f'Synthetic IPC example {i+1} validates')
    mutations = []
    a = json.loads(json.dumps(examples[0])); a['extra'] = 'forbidden'; mutations.append(a)
    a = json.loads(json.dumps(examples[0])); a['protocol']['major'] = 99; mutations.append(a)
    a = json.loads(json.dumps(examples[2])); a['payload']['speech_text'] = 'x' * 281; mutations.append(a)
    a = json.loads(json.dumps(examples[4])); a['payload']['result']['filename'] = '../escape.wav'; mutations.append(a)
    for i, mutant in enumerate(mutations):
        check(not iv.is_valid(mutant), f'Schema negative test {i+1} rejects invalid input')
    permissions = read_json('planning/permissions.json')
    check(all(not value for k,value in permissions.items() if k.endswith('_approved')), 'No ungranted external permissions marked approved')
    evidence = read_json('verification/application-evidence-template.json')
    check(evidence['status'] == 'NOT_RUN' and evidence['code_sha'] is None, 'Application report is unexecuted template')
    manifest_path = ROOT / 'verification' / 'SHA256SUMS.json'
    if manifest_path.exists():
        manifest = read_json('verification/SHA256SUMS.json')['files']
        for name, digest in manifest.items():
            path = (ROOT / name).resolve()
            check(path.is_relative_to(ROOT) and path.is_file(), f'Manifest path exists: {name}')
            if path.is_relative_to(ROOT) and path.is_file():
                check(hashlib.sha256(path.read_bytes()).hexdigest() == digest, f'Checksum verified: {name}')
    else:
        check(False, 'Missing verification/SHA256SUMS.json')
    result = {'scope':'REQUIREMENTS_PACKAGE_ONLY_NOT_APPLICATION_TESTS','status':'PASSED' if not errors else 'FAILED',
              'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'spec_version':'2.0',
              'spec_sha256':hashlib.sha256((ROOT/'IMPLEMENTATION_SPEC.md').read_bytes()).hexdigest(),
              'requirements':len(requirements),'acceptance_cases':len(tests),'work_packets':len(tasks),'behavior_events':len(policy),
              'passed_checks':len(checks),'failed_checks':len(errors),'errors':errors,
              'application_acceptance_status':'ALL_NOT_RUN','checks':checks}
    REPORT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"{result['status']}: {len(checks)} package checks passed; {len(errors)} failed.")
    print('Application tests: NOT RUN. No repository, game, model, device or GPU was exercised.')
    for e in errors: print('ERROR:',e)
    return 1 if errors else 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1)
