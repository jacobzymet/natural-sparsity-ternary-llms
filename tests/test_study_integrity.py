"""Incomplete hardware sweeps must never look like successful measurements."""

import os
import subprocess
from pathlib import Path

import pytest

from scripts.parse_power_study import require_complete_reports


def test_manifest_detects_a_completely_missing_engine(tmp_path):
    (tmp_path / "expected_runs.txt").write_text("baseline__row\nbitmap__row\n")
    (tmp_path / "baseline__row.power.txt").touch()
    with pytest.raises(ValueError, match="missing.*bitmap__row"):
        require_complete_reports(tmp_path, {"baseline__row"})


def test_manifest_rejects_stale_extra_results(tmp_path):
    (tmp_path / "expected_runs.txt").write_text("current\n")
    for run in ("current", "stale"):
        (tmp_path / f"{run}.power.txt").touch()
    with pytest.raises(ValueError, match="unexpected.*stale"):
        require_complete_reports(tmp_path, set())


@pytest.mark.parametrize("manifest", ["", "same\nsame\n"])
def test_empty_or_duplicate_plan_is_rejected(tmp_path, manifest):
    (tmp_path / "expected_runs.txt").write_text(manifest)
    with pytest.raises(ValueError, match="invalid expected-run list"):
        require_complete_reports(tmp_path, {"same"})


def test_legacy_archive_uses_expected_workload_coverage(tmp_path):
    for run in ("baseline__row", "bitmap__row"):
        (tmp_path / f"{run}.power.txt").touch()
    require_complete_reports(tmp_path, {"baseline__row", "bitmap__row"})
    with pytest.raises(ValueError, match="missing.*second_row"):
        require_complete_reports(tmp_path, {"baseline__row", "bitmap__row", "second_row"})


@pytest.mark.skipif(os.name == "nt", reason="The EDA job scheduler runs under Linux Bash")
@pytest.mark.parametrize("codes,jobs,success", [([0, 0, 0], 2, True), ([0, 7], 2, False), ([0, 7], 4, False)])
def test_every_background_worker_status_is_propagated(codes, jobs, success):
    script = f"JOBS={jobs}\nsource synthesis/study_jobs.sh\n"
    script += "\n".join(f"study_launch bash -c 'exit {code}'" for code in codes)
    script += "\nstudy_wait\necho COMPLETE\n"
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert (result.returncode == 0) == success
    assert ("COMPLETE" in result.stdout) == success
