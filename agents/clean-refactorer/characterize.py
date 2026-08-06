#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
characterize.py — scaffold a behavior-preservation net (golden-master / characterization tests).

This is the FIRST move of a clean-refactorer run: before ANY restructuring, you pin the code's
ACTUAL current input->output behavior so a refactor has a rollback oracle. A characterization test
does not assert what the code *should* do — it freezes what it *does today*, so any behavioral drift
during the refactor turns the suite red and you `git revert` (Feathers, "Working Effectively with
Legacy Code").

What this does:
  - Detects the stack (Spring Boot / React+Vite+TS / FastAPI / generic Python|Node).
  - Emits ready-to-fill characterization test scaffolds + a runner into the TARGET repo, using the
    idiomatic golden-master tool for that stack:
        pytest + approvaltests / pytest-snapshot   (Python / FastAPI)
        Vitest snapshot (toMatchSnapshot)          (React + Vite + TS)
        JUnit 5 + ApprovalTests (Approvals.verify) (Spring Boot)
  - The scaffolds capture REAL I/O into approved snapshots on first GREEN run; that's your net.

It is READ-ONLY on existing source: it only CREATES new test/scaffold files (never overwrites
without --force) and prints next steps. It does NOT run the target's build or install its deps.
Missing optional tools are SKIPPED with a logged note — the run never hard-fails on one absent binary.

Usage:
  uv run characterize.py <repo> [--force] [--dry-run]

After running:
  1. Fill the TODO inputs (representative + edge cases) in the emitted scaffolds.
  2. Run the suite once to RECORD the golden snapshots (approve them) and get it GREEN.
  3. Commit it STANDALONE ("test: add characterization tests") — no structural change in that commit.
  4. Only THEN start refactoring; re-run after every slice; revert on red.
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path

TOOL = "characterize"


def log(msg: str) -> None:
    print(f"[{TOOL}] {msg}", file=sys.stderr)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    log("$ " + " ".join(cmd))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


# --------------------------------------------------------------------------- detection
def detect_stack(repo: Path) -> set[str]:
    """Best-effort stack detection (mirrors security-reviewer's heuristics)."""
    s: set[str] = set()
    names = {p.name for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    if "pom.xml" in names or any(repo.rglob("build.gradle*")):
        s.add("java")
        # Spring Boot if any manifest mentions it
        for mani in list(repo.rglob("pom.xml")) + list(repo.rglob("build.gradle*")):
            try:
                if "spring-boot" in mani.read_text("utf-8", errors="ignore"):
                    s.add("spring")
                    break
            except Exception:
                pass
    if "package.json" in names:
        s.add("node")
        try:
            pkg = json.loads(next(repo.rglob("package.json")).read_text("utf-8"))
            dep = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vite" in dep or "@vitejs/plugin-react" in dep:
                s.add("vite")
            if "react" in dep:
                s.add("react")
            if "typescript" in dep:
                s.add("ts")
        except Exception:
            pass
    if any(repo.rglob("*.py")) or "pyproject.toml" in names or "requirements.txt" in names:
        s.add("python")
        for cfg in list(repo.rglob("pyproject.toml")) + list(repo.rglob("requirements.txt")):
            try:
                if "fastapi" in cfg.read_text("utf-8", errors="ignore").lower():
                    s.add("fastapi")
                    break
            except Exception:
                pass
    return s


def write(path: Path, content: str, force: bool, dry: bool) -> bool:
    """Create a file; never clobber unless --force. Returns True if it would/did write."""
    if path.exists() and not force:
        log(f"SKIP (exists, use --force): {path}")
        return False
    if dry:
        log(f"DRY would write: {path}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log(f"wrote: {path}")
    return True


# --------------------------------------------------------------------------- scaffolds
def scaffold_python(repo: Path, fastapi: bool, force: bool, dry: bool) -> list[str]:
    """pytest + approvaltests; FastAPI uses TestClient to characterize routes."""
    out = repo / "tests" / "characterization"
    notes: list[str] = []

    conftest = '''\
"""Characterization-test fixtures. Generated by clean-refactorer/characterize.py.

These tests PIN current behavior (golden master). They assert what the system does TODAY,
not what it "should" do. Treat a failure during a refactor as: behavior changed -> revert.
"""
import pytest
'''
    if fastapi:
        body = '''\
"""
Characterize the FastAPI app's HTTP behavior (status + body) over representative + edge inputs.

Uses approvaltests: the first GREEN run RECORDS each response into a `.approved.txt`; later runs
DIFF against it. Edit IMPORT_APP below to point at your FastAPI instance, fill the CASES, run once
to approve the golden files, commit them STANDALONE, then start refactoring.

    pip/uv:  pytest approvaltests httpx   (and your app deps)
    run:     pytest tests/characterization -q
"""
from approvaltests import verify
from fastapi.testclient import TestClient

# TODO: import your real ASGI app, e.g.  from app.main import app
# from app.main import app  # noqa: E402

# Representative + EDGE inputs. Include: a normal call, empty/missing fields, boundary values,
# an input that triggers an error path, and any weird production input you have.
CASES = [
    # (method, path, json_body_or_None)
    ("GET", "/health", None),
    # ("POST", "/items", {"name": "x", "qty": 0}),          # boundary
    # ("POST", "/items", {}),                                # missing fields (error path)
]


def _client() -> TestClient:
    # return TestClient(app)
    raise NotImplementedError("Wire up `app` import above, then delete this line.")


def test_characterize_http():
    client = _client()
    transcript = []
    for method, path, body in CASES:
        r = client.request(method, path, json=body)
        # Snapshot status + headers-that-are-contract + body. Add anything else observable.
        transcript.append(
            f"{method} {path} {body!r}\\n"
            f"  -> {r.status_code}\\n"
            f"  {r.text}\\n"
        )
    verify("\\n".join(transcript))
'''
    else:
        body = '''\
"""
Characterize a pure function / unit's input->output over representative + edge inputs.

Uses approvaltests: first GREEN run RECORDS the golden `.approved.txt`; later runs diff against it.
Point TARGET at the function under refactor, fill INPUTS (incl. edge cases), approve, commit
STANDALONE, then refactor.

    deps:  pytest approvaltests
    run:   pytest tests/characterization -q
"""
from approvaltests import verify

# TODO: import the unit you are about to refactor.
# from yourpkg.module import target as TARGET

# Representative + EDGE inputs: empty, None, 0/negative, max, the input that throws, etc.
INPUTS = [
    # (),                 # no-arg
    # (0,),
    # (-1,),
    # ("",),
    # (None,),
]


def _call(args):
    # return TARGET(*args)
    raise NotImplementedError("Wire up TARGET import above, then delete this line.")


def test_characterize_unit():
    lines = []
    for args in INPUTS:
        try:
            result = repr(_call(args))
        except Exception as e:  # capturing the error path IS characterizing behavior
            result = f"{type(e).__name__}: {e}"
        lines.append(f"{args!r} -> {result}")
    verify("\\n".join(lines))
'''
    n1 = write(out / "conftest.py", conftest, force, dry)
    fn = "test_characterize_http.py" if fastapi else "test_characterize_unit.py"
    n2 = write(out / fn, body, force, dry)
    if n1 or n2:
        notes.append(f"Python scaffold -> {out}  (deps: pytest approvaltests"
                     + (" httpx" if fastapi else "") + ")")
    return notes


def scaffold_vitest(repo: Path, force: bool, dry: bool) -> list[str]:
    """Vitest snapshot test (React+Vite+TS)."""
    src = repo / "src"
    base = src if src.exists() else repo
    out = base / "__characterization__"
    test = '''\
/**
 * Characterization (golden-master) tests. Generated by clean-refactorer/characterize.py.
 *
 * These PIN current behavior. `toMatchSnapshot()` RECORDS the output on first run into
 * `__snapshots__/`, then diffs against it. During a refactor, a snapshot diff means behavior
 * changed -> revert the slice.
 *
 *   deps:  vitest   (already present in most Vite+TS apps; else: npm i -D vitest)
 *   run:   npx vitest run src/**/__characterization__
 *
 * Cover a pure function/hook/component over representative + EDGE inputs (empty, null, boundary,
 * error path). Replace the TODO target with the real unit, fill CASES, run once to record, then
 * commit the snapshots STANDALONE and start refactoring.
 */
import { describe, it, expect } from "vitest";

// TODO: import the unit you are about to refactor.
// import { target } from "../path/to/unit";
const target = (..._args: unknown[]): unknown => {
  throw new Error("Wire up the real `target` import above, then delete this stub.");
};

const CASES: unknown[][] = [
  // [],          // no-arg
  // [0],
  // [-1],
  // [""],
  // [null],
];

describe("characterization: target", () => {
  for (const args of CASES) {
    it(`pins behavior for ${JSON.stringify(args)}`, () => {
      let result: unknown;
      try {
        result = target(...args);
      } catch (e) {
        result = { error: String(e) }; // capturing the error path IS characterizing behavior
      }
      expect(result).toMatchSnapshot();
    });
  }
});
'''
    if write(out / "characterize.test.ts", test, force, dry):
        return [f"Vitest scaffold -> {out}/characterize.test.ts  (run: npx vitest run)"]
    return []


def scaffold_java(repo: Path, force: bool, dry: bool) -> list[str]:
    """JUnit 5 + ApprovalTests skeleton (Spring Boot)."""
    # Place under a conventional test path; the user moves it into their module if needed.
    pkg_dir = repo / "src" / "test" / "java" / "characterization"
    test = '''\
package characterization;

import org.junit.jupiter.api.Test;
import org.approvaltests.Approvals;

/**
 * Characterization (golden-master) tests. Generated by clean-refactorer/characterize.py.
 *
 * These PIN current behavior. {@code Approvals.verify(...)} RECORDS output into a
 * *.approved.txt on first run, then diffs against it. During a refactor, a diff means
 * behavior changed -> revert the slice.
 *
 * Maven deps (test scope):
 *   org.junit.jupiter:junit-jupiter
 *   com.approvaltests:approvaltests
 * For controllers, prefer @SpringBootTest + MockMvc / @WebMvcTest and verify the response body.
 *
 * Replace the TODO target, fill CASES with representative + EDGE inputs (empty, null, boundary,
 * the input that throws), run once to approve the golden file, commit it STANDALONE, then refactor.
 */
class CharacterizationTest {

    // TODO: construct the unit you are about to refactor.
    // private final YourType target = new YourType(...);

    @Test
    void characterizeUnit() {
        StringBuilder transcript = new StringBuilder();
        // Representative + EDGE inputs:
        Object[][] cases = new Object[][] {
            // { 0 },
            // { -1 },
            // { "" },
            // { null },
        };
        for (Object[] args : cases) {
            String result;
            try {
                // result = String.valueOf(target.method(args[0]));
                throw new UnsupportedOperationException("Wire up target call, then delete this.");
            } catch (Throwable t) { // capturing the error path IS characterizing behavior
                result = t.getClass().getSimpleName() + ": " + t.getMessage();
            }
            transcript.append(java.util.Arrays.deepToString(args))
                      .append(" -> ").append(result).append("\\n");
        }
        Approvals.verify(transcript.toString());
    }
}
'''
    if write(pkg_dir / "CharacterizationTest.java", test, force, dry):
        return [f"JUnit+ApprovalTests skeleton -> {pkg_dir}/CharacterizationTest.java"]
    return []


# --------------------------------------------------------------------------- runner doc
RUNNER_MD = """\
# Behavior-preservation net — how to use these scaffolds

clean-refactorer generated characterization (golden-master) test scaffolds here. They PIN the
code's CURRENT behavior so a refactor has a rollback oracle. Do this BEFORE any restructuring:

1. **Fill the inputs.** Put representative + EDGE cases (empty, null, boundary, error paths, the
   weird production input) into the `CASES`/`INPUTS` lists, and import the real unit/route.
2. **Record the golden snapshots.** Run the suite once. ApprovalTests writes `*.approved.txt`;
   Vitest writes `__snapshots__/`. Inspect them — they should reflect what the code does TODAY.
3. **Get it GREEN, commit it STANDALONE.** One commit, message `test: add characterization tests`,
   with NO structural change. This is your net + your proof.
4. **Refactor on top.** Move in tiny slices (Branch-by-Abstraction / Strangler Fig), re-run the net
   after EVERY slice. Green ⇒ keep. Red ⇒ `git revert` that commit — behavior changed.
5. **Lock boundaries.** Run `fitness_init.py` to add the CI fitness function for your stack.

Run commands:
- Python:  `pytest tests/characterization -q`        (deps: pytest approvaltests [httpx])
- Vitest:  `npx vitest run`                           (TS/React)
- Java:    `mvn -Dtest=CharacterizationTest test`     (deps: junit-jupiter, approvaltests)
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold characterization (golden-master) tests.")
    ap.add_argument("repo")
    ap.add_argument("--force", action="store_true", help="overwrite existing scaffold files")
    ap.add_argument("--dry-run", action="store_true", help="show what would be written, write nothing")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        log(f"no such repo: {repo}")
        return 2

    stacks = detect_stack(repo)
    log(f"detected stacks: {sorted(stacks) or ['?']}")
    if not stacks:
        log("could not detect a supported stack (Spring Boot / React+Vite+TS / FastAPI / Python|Node).")
        log("Scaffold manually: a test that records current I/O over edge inputs into a golden file.")
        return 1

    notes: list[str] = []
    if "python" in stacks:
        notes += scaffold_python(repo, fastapi=("fastapi" in stacks), force=args.force, dry=args.dry_run)
    if "vite" in stacks or ("react" in stacks and "ts" in stacks):
        notes += scaffold_vitest(repo, force=args.force, dry=args.dry_run)
    if "java" in stacks:
        notes += scaffold_java(repo, force=args.force, dry=args.dry_run)

    # A small README next to the project root so the net's usage travels with the repo.
    write(repo / "CHARACTERIZATION.md", RUNNER_MD, args.force, args.dry_run)

    # Optional convenience: surface whether the test runners are installed (skip-on-missing ethos).
    for tool, label in (("pytest", "Python"), ("npx", "Node/Vitest"), ("mvn", "Java/Maven")):
        if not have(tool):
            log(f"note: `{tool}` not on PATH — install it before running the {label} suite.")

    print(json.dumps({
        "stacks": sorted(stacks),
        "scaffolds": notes,
        "next": "Fill inputs -> record golden snapshots -> commit STANDALONE green -> "
                "refactor in tiny slices, re-run after each, revert on red.",
    }, indent=2))
    log("Net scaffolded. Refactor ONLY behind this green net. See CHARACTERIZATION.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
