"""The release workflow must put the wheel and its checksum on the GitHub release (#209).

A consumer that cannot install from an index (the-workshop's workbench runtime,
the-workshop#1120) pins a release asset by URL and sha256. v0.1.0 shipped with no
assets, so there was nothing to pin. These tests read `.github/workflows/release.yml`
and pin the structure that fixes it: build the dist once, check the wheel carries the
released version, and upload wheel + sdist + SHA256SUMS to the release the tag names.

The release is published as GitHub release assets ONLY. The `ragmark` project name on PyPI
belongs to an unrelated project (registered 2026-09-19, not by us), so the old `uv publish`
step failed with 422 invalid-publisher on every release, after the assets were up. It was
removed on purpose; `test_nothing_publishes_to_pypi` keeps it from quietly coming back.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
RELEASED = "steps.release.outputs.released == 'true'"
# What a package-index publish step looks like: `uv publish`, twine, the PyPA publish action,
# or any Trusted Publishing switch. A GitHub release upload matches none of these.
PUBLISH_MARKERS = ("uv publish", "twine", "pypi-publish", "trusted-publishing")


@pytest.fixture(scope="module")
def steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["release"]["steps"]


def _index(steps: list[dict], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in s.get("run", "")]
    assert hits, f"no step runs {needle!r}"
    return hits[0]


def _step(steps: list[dict], needle: str) -> dict:
    return steps[_index(steps, needle)]


def test_the_job_may_write_to_the_release() -> None:
    perms = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["release"]["permissions"]
    assert perms["contents"] == "write"


def test_the_job_requests_no_oidc_token() -> None:
    """`id-token: write` existed only for PyPI Trusted Publishing; nothing else uses it."""
    perms = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["release"]["permissions"]
    assert perms.get("id-token") != "write"


def test_the_dist_is_built_once_and_before_the_upload(steps: list[dict]) -> None:
    builds = [i for i, s in enumerate(steps) if "uv build" in s.get("run", "")]
    assert len(builds) == 1, "build the dist once; every consumer must ship the same bytes"
    assert builds[0] < _index(steps, "gh release upload")


def test_nothing_publishes_to_pypi(steps: list[dict]) -> None:
    """The release is GitHub release assets only; the PyPI `ragmark` name is not ours."""
    publishing = [
        step.get("name", step.get("run", step.get("uses", "?")))
        for step in steps
        if any(
            marker in f"{step.get('run', '')} {step.get('uses', '')}".lower()
            for marker in PUBLISH_MARKERS
        )
    ]
    assert not publishing, f"a step publishes to a package index: {publishing}"


def test_the_upload_attaches_the_wheel_and_a_checksum_to_the_tagged_release(
    steps: list[dict],
) -> None:
    upload = _step(steps, "gh release upload")
    run = upload["run"]
    assert "steps.release.outputs.tag" in run or "RELEASE_TAG" in run
    assert "dist/*.whl" in run
    assert "SHA256SUMS" in run
    assert upload["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"


def _run_step(
    steps: list[dict], needle: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Execute a workflow step's script for real, in `cwd`, the way the runner would.

    The runner is ubuntu (`sha256sum`); a macOS dev box has only `shasum`, so shim it.
    """
    shim = cwd / "_shim"
    shim.mkdir(exist_ok=True)
    if shutil.which("sha256sum") is None:
        tool = shim / "sha256sum"
        tool.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
        tool.chmod(0o755)
    environ = {**os.environ, **(env or {})}
    environ["PATH"] = f"{shim}{os.pathsep}{environ['PATH']}"
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _step(steps, needle)["run"]],
        cwd=cwd,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )


def _dist(cwd: Path, *names: str) -> None:
    (cwd / "dist").mkdir()
    for name in names:
        (cwd / "dist" / name).write_bytes(name.encode())


def test_the_guard_accepts_exactly_the_released_version(steps: list[dict], tmp_path: Path) -> None:
    _dist(tmp_path, "ragmark-0.2.0-py3-none-any.whl", "ragmark-0.2.0.tar.gz")
    done = _run_step(steps, "ragmark-", tmp_path, {"RELEASE_VERSION": "0.2.0"})
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("claimed", ["0.3.0", "0.2", "0.2.0rc1", ""])
def test_the_guard_refuses_a_wheel_of_another_version(
    steps: list[dict], tmp_path: Path, claimed: str
) -> None:
    _dist(tmp_path, "ragmark-0.2.0-py3-none-any.whl")
    done = _run_step(steps, "ragmark-", tmp_path, {"RELEASE_VERSION": claimed})
    assert done.returncode != 0
    assert "is not version" in done.stderr


def test_the_guard_refuses_zero_or_several_wheels(steps: list[dict], tmp_path: Path) -> None:
    _dist(tmp_path, "ragmark-0.2.0.tar.gz")
    none = _run_step(steps, "ragmark-", tmp_path, {"RELEASE_VERSION": "0.2.0"})
    assert none.returncode != 0 and "exactly one wheel" in none.stderr
    (tmp_path / "dist" / "ragmark-0.2.0-py3-none-any.whl").write_bytes(b"a")
    (tmp_path / "dist" / "ragmark-0.2.0-py2-none-any.whl").write_bytes(b"b")
    many = _run_step(steps, "ragmark-", tmp_path, {"RELEASE_VERSION": "0.2.0"})
    assert many.returncode != 0 and "exactly one wheel" in many.stderr


def test_the_checksum_file_lists_the_real_hashes_and_stays_out_of_dist(
    steps: list[dict], tmp_path: Path
) -> None:
    _dist(tmp_path, "ragmark-0.2.0-py3-none-any.whl", "ragmark-0.2.0.tar.gz")
    done = _run_step(steps, "SHA256SUMS", tmp_path)
    assert done.returncode == 0, done.stderr

    listed = dict(
        reversed(line.split(maxsplit=1))
        for line in (tmp_path / "release-assets" / "SHA256SUMS").read_text().splitlines()
    )
    expected = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / "dist").iterdir()
    }
    assert {k.strip(): v for k, v in listed.items()} == expected
    assert not (tmp_path / "dist" / "SHA256SUMS").exists(), "dist/ holds only the built dists"


@pytest.mark.parametrize("needle", ["uv build", "SHA256SUMS", "gh release upload"])
def test_every_post_release_step_only_runs_when_a_release_was_cut(
    steps: list[dict], needle: str
) -> None:
    assert _step(steps, needle).get("if") == RELEASED
