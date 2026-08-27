"""
The committed traceability matrix has to match the source it claims to describe.

ISO/IEC 17025:2017 7.11.2 wants the LIMS validated before introduction and
re-validated when it changes. A matrix that was accurate the day someone
generated it and has drifted since is worse than none: it is a document that
asserts coverage the code no longer has. This makes staleness a build
failure, which is what turns docs/traceability-matrix.md into evidence.

No database and no Django: tools/traceability.py is stdlib-only so it can run
in CI as a plain lint step, and this test stays honest if the app cannot boot.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_the_committed_traceability_matrix_is_up_to_date():
    result = subprocess.run(
        [sys.executable, "tools/traceability.py", "--check"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"{result.stdout}{result.stderr}\n"
        "The traceability matrix no longer matches the source. Regenerate it with:\n"
        "    cd backend && python tools/traceability.py --write"
    )
