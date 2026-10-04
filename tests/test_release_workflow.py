"""The release workflow must put the wheel and its checksum on the GitHub release (#209).

A consumer that cannot install from an index (the-workshop's workbench runtime,
the-workshop#1120) pins a release asset by URL and sha256. v0.1.0 shipped with no
assets, so there was nothing to pin. These tests read `.github/workflows/release.yml`
and pin the structure that fixes it: build the dist once, check the wheel carries the
released version, upload wheel + SHA256SUMS to the release the tag names, and do all
of it BEFORE the PyPI publish, which fails until Trusted Publishing is configured and
must not take the assets down with it.
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


def test_the_dist_is_built_once_and_before_both_consumers(steps: list[dict]) -> None:
    builds = [i for i, s in enumerate(steps) if "uv build" in s.get("run", "")]
    assert len(builds) == 1, "build the dist once; upload and publish must ship the same bytes"
    assert builds[0] < _index(steps, "gh release upload")
    assert builds[0] < _index(steps, "uv publish")


def test_assets_are_uploaded_before_the_pypi_publish(steps: list[dict]) -> None:
    assert _index(steps, "gh release upload") < _index(steps, "uv publish")


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
    assert not (tmp_path / "dist" / "SHA256SUMS").exists(), "PyPI would reject it in dist/"


@pytest.mark.parametrize("needle", ["uv build", "SHA256SUMS", "gh release upload", "uv publish"])
def test_every_post_release_step_only_runs_when_a_release_was_cut(
    steps: list[dict], needle: str
) -> None:
    assert _step(steps, needle).get("if") == RELEASED
