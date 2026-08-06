#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
behavior_diff.py — the performance agent's behavior-preservation ORACLE.

Captures a target's *observable output* (golden I/O) over representative + edge inputs,
once BEFORE a perf change and once AFTER, and asserts the two captures are byte-identical.
If any byte drifts, the optimization changed behavior and MUST be reverted — speed is never
worth a behavior change.

stdlib only, self-contained (the clean-refactorer agent reuses this same idea — keep it
copyable). It does not know what "correct" is; it only knows the AFTER must equal the BEFORE.

A "case" is one invocation of the target. The target is whatever you can run from a shell and
read deterministic output from: a CLI, an HTTP endpoint (via curl), a script. You describe the
cases in a small JSON spec; this tool runs them and hashes the captured output.

Spec (cases.json):
  {
    "name": "parse_invoice",
    "normalize": ["strip_trailing_ws"],          # optional output normalizers (see NORMALIZERS)
    "cases": [
      {"id": "happy",      "cmd": ["python", "parse.py", "samples/a.csv"]},
      {"id": "empty",      "cmd": ["python", "parse.py", "samples/empty.csv"]},
      {"id": "unicode",    "cmd": ["python", "parse.py", "samples/utf8.csv"]},
      {"id": "http-list",  "cmd": ["curl", "-s", "http://localhost:8000/items?limit=3"]},
      {"id": "stdin-case", "cmd": ["python", "parse.py", "-"], "stdin": "1,2,3\n"}
    ]
  }

Workflow:
  uv run behavior_diff.py capture cases.json --label before --out goldens/
  # ... apply the ONE perf fix ...
  uv run behavior_diff.py capture cases.json --label after  --out goldens/
  uv run behavior_diff.py assert goldens/before.json goldens/after.json
  #   exit 0 = byte-identical (safe to keep the fix) ; exit 1 = DRIFT (revert)

Edge inputs to ALWAYS include (this is the whole point — fast on the happy path, wrong on the
edge, is the classic bad optimization): empty, single-element, large, unicode/multibyte,
negative/zero numbers, null/None, duplicate keys, and the slow-path input the profiler flagged.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path


def log(msg: str) -> None:
    print(f"[behavior_diff] {msg}", file=sys.stderr)


# --- output normalizers -------------------------------------------------------
# Sometimes legitimately non-deterministic bytes (timestamps, run durations) appear in output
# and would cause false DRIFT. Opt-in normalizers strip ONLY those. Use the narrowest one that
# works; an over-broad normalizer can hide a real behavior change, which defeats the oracle.
def _strip_trailing_ws(b: bytes) -> bytes:
    return b"\n".join(line.rstrip() for line in b.split(b"\n"))


def _sort_lines(b: bytes) -> bytes:
    # only when the contract genuinely does NOT promise order (e.g. a set serialized to lines)
    return b"\n".join(sorted(b.split(b"\n")))


def _collapse_ws(b: bytes) -> bytes:
    return b" ".join(b.split())


NORMALIZERS = {
    "strip_trailing_ws": _strip_trailing_ws,
    "sort_lines": _sort_lines,
    "collapse_ws": _collapse_ws,
}


def normalize(raw: bytes, names: list[str]) -> bytes:
    out = raw
    for n in names:
        fn = NORMALIZERS.get(n)
        if fn is None:
            log(f"WARN unknown normalizer {n!r} (ignored)")
            continue
        out = fn(out)
    return out


def run_case(case: dict, normalizers: list[str], timeout: int) -> dict:
    cmd = case["cmd"]
    stdin = case.get("stdin")
    cid = case.get("id", " ".join(map(str, cmd))[:60])
    t0 = time.perf_counter()
    try:
        p = subprocess.run(
            cmd,
            input=stdin.encode("utf-8") if isinstance(stdin, str) else stdin,
            capture_output=True,
            timeout=timeout,
        )
        rc, out, err = p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        rc, out, err = 127, b"", f"not found: {cmd[0]}".encode()
    except subprocess.TimeoutExpired:
        rc, out, err = 124, b"", b"timeout"
    dt = time.perf_counter() - t0

    norm = normalize(out, normalizers)
    # The behavioral fingerprint = exit code + normalized stdout + raw stderr. stderr is part of
    # observable behavior (an error message changing IS a behavior change), but it is NOT
    # normalized — errors should be exact. Timing (dt) is recorded for the perf delta but is
    # deliberately EXCLUDED from the hash, since speed is what we are allowed to change.
    h = hashlib.sha256()
    h.update(str(rc).encode())
    h.update(b"\0")
    h.update(norm)
    h.update(b"\0")
    h.update(err)
    return {
        "id": cid,
        "returncode": rc,
        "sha256": h.hexdigest(),
        "stdout_len": len(out),
        "stderr": err.decode("utf-8", "replace")[:500],
        "seconds": round(dt, 6),
    }


def capture(spec_path: Path, label: str, out_dir: Path, timeout: int) -> int:
    spec = json.loads(spec_path.read_text("utf-8"))
    normalizers = spec.get("normalize", [])
    cases = spec.get("cases", [])
    if not cases:
        log("spec has no cases")
        return 2
    log(f"capturing {len(cases)} case(s), label={label}, normalizers={normalizers or '-'}")
    results = [run_case(c, normalizers, timeout) for c in cases]
    doc = {
        "name": spec.get("name", spec_path.stem),
        "label": label,
        "normalize": normalizers,
        "cases": results,
        "total_seconds": round(sum(r["seconds"] for r in results), 6),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{label}.json"
    out_file.write_text(json.dumps(doc, indent=2), "utf-8")
    log(f"wrote {out_file}  (total {doc['total_seconds']}s)")
    print(json.dumps({"label": label, "cases": len(results),
                      "total_seconds": doc["total_seconds"], "out": str(out_file)}, indent=2))
    return 0


def assert_identical(before_path: Path, after_path: Path) -> int:
    before = json.loads(before_path.read_text("utf-8"))
    after = json.loads(after_path.read_text("utf-8"))
    b_by_id = {c["id"]: c for c in before["cases"]}
    a_by_id = {c["id"]: c for c in after["cases"]}

    drift: list[str] = []
    missing = set(b_by_id) ^ set(a_by_id)
    for cid in sorted(missing):
        drift.append(f"case set changed: {cid!r} present in only one capture")

    speedups: list[tuple[str, float, float]] = []
    for cid in sorted(set(b_by_id) & set(a_by_id)):
        b, a = b_by_id[cid], a_by_id[cid]
        if b["sha256"] != a["sha256"]:
            drift.append(
                f"OUTPUT DRIFT in {cid!r}: rc {b['returncode']}->{a['returncode']}, "
                f"len {b['stdout_len']}->{a['stdout_len']} (hash differs)"
            )
        speedups.append((cid, b["seconds"], a["seconds"]))

    print("# behavior-equivalence proof")
    print(f"  before: {before_path}  ({before.get('total_seconds')}s)")
    print(f"  after:  {after_path}  ({after.get('total_seconds')}s)")
    bt = before.get("total_seconds") or 0.0
    at = after.get("total_seconds") or 0.0
    if bt > 0:
        pct = (bt - at) / bt * 100.0
        print(f"  wall-time delta: {bt:.4f}s -> {at:.4f}s  ({pct:+.1f}%)")
    print()
    for cid, b_s, a_s in speedups:
        mark = "ok " if b_by_id[cid]["sha256"] == a_by_id[cid]["sha256"] else "DRIFT"
        print(f"  [{mark}] {cid:<24} {b_s:.4f}s -> {a_s:.4f}s")

    if drift:
        print("\nRESULT: BEHAVIOR DRIFT — REVERT THE CHANGE", file=sys.stderr)
        for d in drift:
            print("  ! " + d, file=sys.stderr)
        return 1

    if bt > 0 and at >= bt:
        # identical behavior but no speed win → the change earned nothing; revert per prime directive.
        print("\nRESULT: behavior preserved, but NO measured speedup — revert (no value).",
              file=sys.stderr)
        return 2

    print("\nRESULT: byte-identical behavior + measured speedup — safe to keep.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Behavior-preservation oracle for perf changes.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="run cases and record a golden capture")
    cap.add_argument("spec", help="cases.json spec")
    cap.add_argument("--label", required=True, help="e.g. before / after")
    cap.add_argument("--out", default="goldens", help="output dir for <label>.json")
    cap.add_argument("--timeout", type=int, default=300)

    asrt = sub.add_parser("assert", help="assert two captures are byte-identical")
    asrt.add_argument("before")
    asrt.add_argument("after")

    args = ap.parse_args()
    if args.cmd == "capture":
        return capture(Path(args.spec), args.label, Path(args.out), args.timeout)
    if args.cmd == "assert":
        return assert_identical(Path(args.before), Path(args.after))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
