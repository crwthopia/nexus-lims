"""
The entrypoint and healthcheck scripts.

These are shell, not Python, and nothing else exercises them: the image
job in CI boots a container per role, which proves the happy paths but
takes a full build to tell you about a typo. These run in a second.

The scripts are tested by running them with a stub `exec` target on PATH,
so the dispatch is checked without starting gunicorn or Celery. What is
being asserted is the *decision* -- which command each role resolves to,
and that migrations run before the roles that need a schema -- not the
behaviour of the programs it hands off to.
"""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ENTRYPOINT = BACKEND / "docker-entrypoint.sh"
HEALTHCHECK = BACKEND / "docker-healthcheck.sh"


@pytest.fixture
def fake_bin(tmp_path):
    """
    A PATH containing stubs for everything the scripts exec.

    Each stub prints how it was called and exits 0, so a test can assert on
    the command line the script built rather than on side effects.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gunicorn", "celery", "python", "curl", "hostname"):
        stub = bin_dir / name
        stub.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo "CALLED {name} $@"
                exit 0
                """
            )
        )
        stub.chmod(0o755)
    # hostname has to return something usable for the worker healthcheck.
    (bin_dir / "hostname").write_text("#!/bin/sh\necho worker-1\n")
    (bin_dir / "hostname").chmod(0o755)
    return bin_dir


def run_script(script, fake_bin, env=None, args=()):
    environment = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(fake_bin.parent),
    }
    environment.update(env or {})
    return subprocess.run(
        [shutil.which("sh"), str(script), *args],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        cwd=str(fake_bin.parent),
    )


# --- entrypoint -----------------------------------------------------------

def test_the_default_role_is_web(fake_bin):
    result = run_script(ENTRYPOINT, fake_bin)

    assert "CALLED gunicorn" in result.stdout
    assert "config.wsgi:application" in result.stdout


def test_web_migrates_before_serving(fake_bin):
    result = run_script(ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "web"})

    # Order matters: serving traffic against an unmigrated schema is the
    # failure this prevents.
    migrate_at = result.stdout.index("CALLED python manage.py deploy_migrate")
    serve_at = result.stdout.index("CALLED gunicorn")
    assert migrate_at < serve_at


def test_the_worker_also_migrates_first(fake_bin):
    # A worker runs the same ORM against the same schema, so it needs the
    # migration as much as the web tier does.
    result = run_script(ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "worker"})

    assert "CALLED python manage.py deploy_migrate" in result.stdout
    assert "CALLED celery -A config worker" in result.stdout


def test_beat_does_not_migrate(fake_bin):
    # Beat owns no schema; racing the web tier to migrate buys nothing.
    result = run_script(ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "beat"})

    assert "deploy_migrate" not in result.stdout
    assert "CALLED celery -A config beat" in result.stdout


def test_migrations_on_start_can_be_turned_off(fake_bin):
    # For a platform that runs migrations as its own release step and would
    # rather the app containers not touch the database at all.
    result = run_script(
        ENTRYPOINT, fake_bin,
        {"NEXUSLIMS_ROLE": "web", "NEXUSLIMS_MIGRATE_ON_START": "false"},
    )

    assert "deploy_migrate" not in result.stdout
    assert "CALLED gunicorn" in result.stdout


def test_the_migrate_role_migrates_and_does_not_serve(fake_bin):
    result = run_script(ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "migrate"})

    assert "CALLED python manage.py deploy_migrate" in result.stdout
    assert "CALLED gunicorn" not in result.stdout
    assert "CALLED celery" not in result.stdout


def test_an_explicit_command_wins_over_the_role(fake_bin):
    """
    `docker run <image> python manage.py shell` has to work.

    This test used to set NEXUSLIMS_ROLE to a bogus value and pass a
    command, which took the unknown-role branch and proved nothing about
    real usage. Nobody sets a fake role; they just pass a command, and the
    role stays at its default. CI found the gap the hard way: with an
    ENTRYPOINT in place, `docker run <image> python manage.py check
    --deploy` arrived here as "$@", the default web role swallowed it, and
    the entrypoint tried to migrate against a database that step does not
    provide.
    """
    result = run_script(ENTRYPOINT, fake_bin, args=("python", "manage.py", "shell"))

    assert "CALLED python manage.py shell" in result.stdout
    assert "CALLED gunicorn" not in result.stdout
    assert "deploy_migrate" not in result.stdout


def test_a_command_beats_an_explicitly_set_role_too(fake_bin):
    # Even with a real role set, an explicit command is what was asked for.
    result = run_script(
        ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "worker"},
        args=("python", "manage.py", "check"),
    )

    assert "CALLED python manage.py check" in result.stdout
    assert "CALLED celery" not in result.stdout


def test_an_unknown_role_with_no_command_fails_loudly(fake_bin):
    # Starting nothing quietly would look like a healthy deploy that never
    # serves anything.
    result = run_script(ENTRYPOINT, fake_bin, {"NEXUSLIMS_ROLE": "nonsense"})

    assert result.returncode == 1
    assert "unknown NEXUSLIMS_ROLE" in result.stderr


def test_gunicorn_settings_come_from_the_environment(fake_bin):
    result = run_script(
        ENTRYPOINT, fake_bin,
        {"NEXUSLIMS_ROLE": "web", "NEXUSLIMS_MIGRATE_ON_START": "false",
         "GUNICORN_WORKERS": "7", "PORT": "9001"},
    )

    assert "--workers 7" in result.stdout
    assert "0.0.0.0:9001" in result.stdout


# --- healthcheck ----------------------------------------------------------

def test_the_web_healthcheck_probes_liveness_not_readiness(fake_bin):
    result = run_script(HEALTHCHECK, fake_bin, {"NEXUSLIMS_ROLE": "web"})

    # /readyz would restart the container whenever Postgres hiccuped.
    assert "/healthz" in result.stdout
    assert "/readyz" not in result.stdout


def test_the_worker_healthcheck_pings_this_worker_specifically(fake_bin):
    result = run_script(HEALTHCHECK, fake_bin, {"NEXUSLIMS_ROLE": "worker"})

    # Without -d, a reply from any worker on the broker satisfies the check
    # and a wedged worker in a pool looks healthy.
    assert "inspect ping" in result.stdout
    assert "-d celery@worker-1" in result.stdout


def test_the_beat_healthcheck_looks_for_its_schedule_file(fake_bin, tmp_path):
    schedule = tmp_path / "celerybeat-schedule"

    missing = run_script(
        HEALTHCHECK, fake_bin,
        {"NEXUSLIMS_ROLE": "beat", "CELERY_BEAT_SCHEDULE_FILE": str(schedule)},
    )
    assert missing.returncode == 1

    schedule.write_text("")
    present = run_script(
        HEALTHCHECK, fake_bin,
        {"NEXUSLIMS_ROLE": "beat", "CELERY_BEAT_SCHEDULE_FILE": str(schedule)},
    )
    assert present.returncode == 0


def test_the_beat_healthcheck_accepts_the_shelve_suffixes(fake_bin, tmp_path):
    # Depending on the platform's dbm implementation, beat's shelve writes
    # celerybeat-schedule, .db or .dat. Checking only the bare name would
    # report a perfectly healthy scheduler as dead.
    schedule = tmp_path / "celerybeat-schedule"
    (tmp_path / "celerybeat-schedule.db").write_text("")

    result = run_script(
        HEALTHCHECK, fake_bin,
        {"NEXUSLIMS_ROLE": "beat", "CELERY_BEAT_SCHEDULE_FILE": str(schedule)},
    )

    assert result.returncode == 0


def test_an_unknown_role_is_unhealthy_rather_than_silently_ok(fake_bin):
    # Reporting healthy for a misconfigured role hides the misconfiguration.
    result = run_script(HEALTHCHECK, fake_bin, {"NEXUSLIMS_ROLE": "nonsense"})

    assert result.returncode == 1
    assert "no healthcheck defined" in result.stderr
