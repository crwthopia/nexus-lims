"""
Generate the requirement -> implementation -> test traceability matrix that
ISO/IEC 17025:2017 7.11.2 asks for.

7.11.2 requires a laboratory information management system to be validated
for functionality before introduction, and re-validated whenever it changes.
An assessor asks two questions of that claim: *which* requirement does each
test discharge, and is there a requirement with nothing testing it. A test
suite alone answers neither -- the mapping lives in docstrings and comments,
where nobody can audit it in aggregate.

This reads that mapping out of the source and writes it down. It is
deliberately a *reporter*, not a database: the requirement IDs stay in the
code next to what implements them, so they cannot drift out of sync with a
separately maintained spreadsheet. Regenerating is the whole update process,
and tests/test_traceability.py fails CI when the committed matrix no longer
matches what the source says -- which is what makes the matrix evidence
rather than documentation.

Stdlib only, and it imports no Django: this has to run in CI without a
database, and an evidence generator that needs the application to boot is
one that stops working exactly when you need it.

Attribution rules (stated here because a matrix nobody can reproduce is not
evidence):

  Python tests (ast, so a commented-out test is not counted as coverage)
    1. Requirement IDs in the module docstring cover every test in it.
    2. A section banner -- a comment between two top-level statements that
       both names a requirement and contains `---` -- covers every test
       after it until the next banner.
    3. A non-banner comment immediately before a test covers that test only.
    4. Requirement IDs anywhere inside a test's own lines cover that test.

  TypeScript tests (regex; there is no TS parser in the stdlib)
    5. Requirement IDs in the file header (before the first `describe`/`it`)
       cover every test in the file.
    6. Requirement IDs inside an `it(...)`/`test(...)` body cover that test.

  Implementation references
    7. Any requirement ID in non-test application source is recorded as an
       implementation site, with its file and line.

Rule 2 is the one that can over-attribute, and the risk runs the dangerous
way -- a matrix claiming coverage that does not exist is worse than one
admitting a gap -- so it is deliberately narrow: an ordinary FR-bearing
comment does not open a section, only a banner does.

Usage:
    python tools/traceability.py --check     # exit 1 if the committed docs drift
    python tools/traceability.py --write     # regenerate docs/
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO_ROOT / "backend"

# Where requirements are implemented, and where they are verified. Kept
# explicit rather than globbing the repo: a stray requirement ID in a
# scratch file should not silently become evidence.
IMPLEMENTATION_ROOTS = [
    BACKEND / "apps",
    BACKEND / "config",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "customer-portal" / "src",
]
TEST_ROOTS = [
    BACKEND / "tests",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "customer-portal" / "src",
]

MATRIX_MD = REPO_ROOT / "docs" / "traceability-matrix.md"
MATRIX_CSV = REPO_ROOT / "docs" / "traceability-matrix.csv"

# FR-E17-01, and the compound form FR-E17-01/03 that means two requirements
# rather than one with a slash in its name.
REQUIREMENT_RE = re.compile(r"\bFR-([A-Z]+\d+)-(\d+)((?:/\d+)+)?\b")

CLAUSE_PATTERNS = [
    (re.compile(r"ISO/IEC 17025:2017\s+(\d+(?:\.\d+)*)"), "ISO/IEC 17025:2017 {}"),
    (re.compile(r"ISO 17025[^\n]{0,12}?(\d+(?:\.\d+)+)"), "ISO/IEC 17025:2017 {}"),
    (re.compile(r"ASTM E1578-18(?:\s+Section)?\s+(\d+(?:\.\d+)*)"), "ASTM E1578-18 {}"),
    (re.compile(r"Blueprint\s+Section\s+(\d+(?:\.\d+)*[a-z]?)"), "Blueprint Section {}"),
]

BANNER_RE = re.compile(r"^\s*#.*---")
TS_TEST_RE = re.compile(r"""^\s*(?:it|test)(?:\.\w+)?\s*\(\s*['"`](.+?)['"`]""", re.M)
TS_BLOCK_START_RE = re.compile(r"""^\s*(?:it|test|describe)(?:\.\w+)?\s*\(""", re.M)


def requirements_in(text: str) -> set[str]:
    """Every requirement ID in `text`, expanding the FR-E17-01/03 compound form."""
    found = set()
    for group, first, extra in REQUIREMENT_RE.findall(text):
        found.add(f"FR-{group}-{first}")
        for suffix in re.findall(r"\d+", extra or ""):
            found.add(f"FR-{group}-{suffix}")
    return found


def clauses_in(text: str) -> set[str]:
    found = set()
    for pattern, template in CLAUSE_PATTERNS:
        for match in pattern.findall(text):
            found.add(template.format(match))
    return found


@dataclass
class Requirement:
    id: str
    clauses: set[str] = field(default_factory=set)
    implementations: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple:
        group, number = self.id.removeprefix("FR-").split("-")
        letters = "".join(c for c in group if c.isalpha())
        digits = "".join(c for c in group if c.isdigit())
        return (letters, int(digits), int(number))


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_test_file(path: Path) -> bool:
    if path.suffix == ".py":
        return path.name.startswith("test_") or path.parent.name == "tests"
    return ".test." in path.name


def iter_source_files(roots: list[Path], suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for suffix in suffixes:
            files.extend(p for p in root.rglob(f"*{suffix}") if "node_modules" not in p.parts)
    return sorted(set(files))


# --- Citation context ------------------------------------------------------

def clause_context(text: str, requirement_ids: set[str]) -> dict[str, set[str]]:
    """
    Standard clauses cited in the same paragraph as a requirement ID.

    Proximity, not inference: the citation and the requirement have to appear
    in the same block of prose for the mapping to be recorded, so a clause
    mentioned elsewhere in the file is not silently attached to every
    requirement in it.
    """
    mapping: dict[str, set[str]] = defaultdict(set)
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph_clauses = clauses_in(paragraph)
        if not paragraph_clauses:
            continue
        for requirement in requirements_in(paragraph) & requirement_ids:
            mapping[requirement] |= paragraph_clauses
    return mapping


# --- Python tests ----------------------------------------------------------

def scan_python_tests(path: Path, requirements: dict[str, Requirement]) -> None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # a test file that will not parse cannot be evidence
        print(f"warning: skipping unparsable {rel(path)}: {exc}", file=sys.stderr)
        return

    lines = source.splitlines()
    module_requirements = requirements_in(ast.get_docstring(tree) or "")

    section_requirements: set[str] = set()
    previous_end = 0

    for node in tree.body:
        first_line = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
        leading = "\n".join(lines[previous_end:first_line - 1])
        previous_end = node.end_lineno or first_line

        leading_requirements = requirements_in(leading)
        if leading_requirements:
            # A banner opens a section that carries forward; any other
            # FR-bearing comment applies to the next test and stops there.
            if any(BANNER_RE.match(line) and requirements_in(line) for line in leading.splitlines()):
                section_requirements = leading_requirements
                leading_requirements = set()

        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
            continue

        body = "\n".join(lines[first_line - 1:node.end_lineno])
        covered = module_requirements | section_requirements | leading_requirements | requirements_in(body)
        for requirement_id in covered:
            requirements.setdefault(requirement_id, Requirement(requirement_id))
            requirements[requirement_id].tests.append(f"{rel(path)}::{node.name}")


# --- TypeScript tests ------------------------------------------------------

def scan_typescript_tests(path: Path, requirements: dict[str, Requirement]) -> None:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    first_block = TS_BLOCK_START_RE.search(source)
    header = source[:first_block.start()] if first_block else source
    file_requirements = requirements_in(header)

    starts = [(m.start(), m.group(1)) for m in TS_TEST_RE.finditer(source)]
    for index, (offset, name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(source)
        covered = file_requirements | requirements_in(source[offset:end])
        line_number = source.count("\n", 0, offset) + 1
        for requirement_id in covered:
            requirements.setdefault(requirement_id, Requirement(requirement_id))
            requirements[requirement_id].tests.append(f"{rel(path)}:{line_number} {name}")
    del lines


# --- Implementation sites --------------------------------------------------

def scan_implementation(path: Path, requirements: dict[str, Requirement]) -> None:
    source = path.read_text(encoding="utf-8")
    file_requirements = requirements_in(source)
    if not file_requirements:
        return

    contexts = clause_context(source, file_requirements)
    seen: set[str] = set()
    for number, line in enumerate(source.splitlines(), start=1):
        for requirement_id in requirements_in(line):
            requirements.setdefault(requirement_id, Requirement(requirement_id))
            requirement = requirements[requirement_id]
            requirement.clauses |= contexts.get(requirement_id, set())
            if requirement_id not in seen:
                requirement.implementations.append(f"{rel(path)}:{number}")
                seen.add(requirement_id)


def collect() -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}

    for path in iter_source_files(IMPLEMENTATION_ROOTS, (".py", ".ts", ".tsx")):
        if is_test_file(path) or "migrations" in path.parts:
            continue
        scan_implementation(path, requirements)

    # Migrations are implementation too -- the RLS policies and the
    # append-only grants exist nowhere else -- but they are scanned
    # separately so a schema change is visibly a schema change.
    for path in iter_source_files([BACKEND / "apps"], (".py",)):
        if "migrations" in path.parts and path.name != "__init__.py":
            scan_implementation(path, requirements)

    for path in iter_source_files(TEST_ROOTS, (".py", ".ts", ".tsx")):
        if not is_test_file(path):
            continue
        if path.suffix == ".py":
            scan_python_tests(path, requirements)
        else:
            scan_typescript_tests(path, requirements)

    return requirements


# --- Rendering -------------------------------------------------------------

def render_markdown(requirements: dict[str, Requirement]) -> str:
    ordered = sorted(requirements.values(), key=lambda r: r.sort_key)
    untested = [r for r in ordered if not r.tests]
    unimplemented = [r for r in ordered if not r.implementations]

    out = io.StringIO()
    write = out.write

    write("# Requirement traceability matrix\n\n")
    write(
        "Generated by `python tools/traceability.py --write`. **Do not edit by hand** — "
        "`backend/tests/test_traceability.py` fails when this file no longer matches the "
        "source, which is what makes it evidence rather than documentation.\n\n"
    )
    write(
        "Evidence for **ISO/IEC 17025:2017 7.11.2** (a laboratory information management "
        "system shall be validated for functionality before introduction, and changes "
        "authorized, documented and validated before implementation). It answers the two "
        "questions an assessor asks of that claim: which test discharges each requirement, "
        "and which requirement has nothing verifying it.\n\n"
    )
    write(
        "**What this is not.** A traceability matrix is one input to a validation report, "
        "not the report. It records that a requirement has a verifying test; it does not "
        "record who authorized the change, who reviewed the result, or when the run was "
        "witnessed. Those are 7.11.2's other half and live in the change-control record.\n\n"
    )
    write("Requirement IDs are read from the source itself, so they cannot drift out of sync ")
    write("with the code. The attribution rules are documented in `backend/tools/traceability.py`.\n\n")
    write(
        "**Granularity.** Where a test module's docstring names a requirement, every test in "
        "that module is recorded against it — the module is the unit of grouping this codebase "
        "uses, not each individual assertion. So a count of 20 means twenty tests run in "
        "service of that requirement, not twenty independent proofs of it.\n\n"
    )

    write("## Summary\n\n")
    write("| | Count |\n|---|---:|\n")
    write(f"| Requirements referenced in source | {len(ordered)} |\n")
    write(f"| With at least one verifying test | {len(ordered) - len(untested)} |\n")
    write(f"| **With no verifying test** | **{len(untested)}** |\n")
    write(f"| With no implementation reference | {len(unimplemented)} |\n")
    write(f"| Test references recorded | {sum(len(r.tests) for r in ordered)} |\n\n")

    if untested:
        write("### Requirements with no verifying test\n\n")
        write(
            "Each of these is either a requirement genuinely without a test, or a test that "
            "verifies it without citing the ID. Both are worth closing: an assessor cannot "
            "tell the two apart, and neither can the next person to change the code.\n\n"
        )
        for requirement in untested:
            sites = ", ".join(f"`{s}`" for s in requirement.implementations[:3]) or "_no reference in source_"
            write(f"- **{requirement.id}** — implemented at {sites}\n")
        write("\n")

    write("## Matrix\n\n")
    write("| Requirement | Cited clauses | Implementation | Verifying tests |\n")
    write("|---|---|---|---:|\n")
    for requirement in ordered:
        clauses = "<br>".join(sorted(requirement.clauses)) or "—"
        sites = "<br>".join(f"`{s}`" for s in requirement.implementations[:4]) or "—"
        if len(requirement.implementations) > 4:
            sites += f"<br>_+{len(requirement.implementations) - 4} more_"
        count = len(requirement.tests) or "**none**"
        write(f"| **{requirement.id}** | {clauses} | {sites} | {count} |\n")
    write("\n")

    write("## Verifying tests, by requirement\n\n")
    for requirement in ordered:
        write(f"### {requirement.id}\n\n")
        if requirement.clauses:
            write(f"Cited clauses: {', '.join(sorted(requirement.clauses))}\n\n")
        if not requirement.tests:
            write("**No verifying test cites this requirement.**\n\n")
            continue
        for test in sorted(set(requirement.tests)):
            write(f"- `{test}`\n")
        write("\n")

    return out.getvalue()


def render_csv(requirements: dict[str, Requirement]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["requirement", "clauses", "implementation", "test"])
    for requirement in sorted(requirements.values(), key=lambda r: r.sort_key):
        clauses = "; ".join(sorted(requirement.clauses))
        implementation = "; ".join(requirement.implementations)
        if not requirement.tests:
            writer.writerow([requirement.id, clauses, implementation, ""])
            continue
        for test in sorted(set(requirement.tests)):
            writer.writerow([requirement.id, clauses, implementation, test])
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="regenerate the committed matrix")
    group.add_argument("--check", action="store_true", help="exit 1 if the committed matrix is stale")
    args = parser.parse_args()

    requirements = collect()
    markdown = render_markdown(requirements)
    csv_text = render_csv(requirements)

    if args.write:
        MATRIX_MD.parent.mkdir(parents=True, exist_ok=True)
        MATRIX_MD.write_text(markdown, encoding="utf-8")
        MATRIX_CSV.write_text(csv_text, encoding="utf-8")
        untested = sum(1 for r in requirements.values() if not r.tests)
        print(f"wrote {rel(MATRIX_MD)} and {rel(MATRIX_CSV)}: "
              f"{len(requirements)} requirements, {untested} with no verifying test")
        return 0

    stale = [
        rel(path)
        for path, expected in ((MATRIX_MD, markdown), (MATRIX_CSV, csv_text))
        if not path.exists() or path.read_text(encoding="utf-8") != expected
    ]
    if stale:
        print("traceability matrix is stale: " + ", ".join(stale), file=sys.stderr)
        print("regenerate with: python tools/traceability.py --write", file=sys.stderr)
        return 1
    print("traceability matrix is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
