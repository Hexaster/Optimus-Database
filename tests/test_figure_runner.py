"""Exercise image publication and backfills without paid model calls or a database."""
import importlib.util
import json
from pathlib import Path

import pytest

from cart_db.artifacts import artifact_manifest, checksum, verify_artifacts
from cart_db.pipeline import write_json

spec = importlib.util.spec_from_file_location("figure_runner", Path(__file__).parents[1] / "scripts/run_extraction_agent.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def bundle(directory, source):
    """Create a valid empty scientific result and explicitly reviewed no-image inventory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data.jsonl").write_text("")
    (directory / "original.jsonl").write_text("")
    (directory / "reasoning.md").write_text("Source inspected; no scientific records.")
    (directory / "figures.jsonl").write_text("")
    (directory / "img").mkdir(exist_ok=True)
    write_json(directory / "source_manifest.json", artifact_manifest(directory, source))


def success():
    """Return the runner's normal transport result without spending model tokens."""
    return dict(ok=True, reason="", usage=runner.empty_usage(), usage_known=True, cost=0.0)


def test_full_run_requires_and_publishes_figures(tmp_path, monkeypatch):
    """A normal run publishes its validated image inventory and manifest together."""
    source = tmp_path / "paper.md"
    source.write_text("No figures in this synthetic document.")

    def fake(path, *, out_dir, **kwargs):
        """Stand in for the coordinator after its image subagent has completed."""
        bundle(out_dir, path)
        return success()

    monkeypatch.setattr(runner, "_run_agent", fake)
    result = runner.run_one(source, out_dir=tmp_path / "output", timeout=30, budget=None)
    assert result["ok"], result
    verify_artifacts(tmp_path / "output/paper", source)


def test_missing_figures_preserves_previous_output(tmp_path, monkeypatch):
    """A coordinator that forgets its image task cannot replace a good existing bundle."""
    source = tmp_path / "paper.md"
    source.write_text("No figures.")
    final = tmp_path / "output/paper"
    bundle(final, source)
    previous = (final / "source_manifest.json").read_bytes()

    def fake(path, *, out_dir, **kwargs):
        """Write only old-format artifacts to simulate a missing image subagent result."""
        (out_dir / "data.jsonl").write_text("")
        (out_dir / "reasoning.md").write_text("New attempt.")
        return success()

    monkeypatch.setattr(runner, "_run_agent", fake)
    result = runner.run_one(source, out_dir=tmp_path / "output", timeout=30, budget=None, validation_retries=0)
    assert not result["ok"]
    assert (final / "source_manifest.json").read_bytes() == previous
    verify_artifacts(final, source)


def test_backfill_preserves_data_and_producer(tmp_path, monkeypatch):
    """An old checksummed result gains images without data normalization or a new UUID pass."""
    source = tmp_path / "paper.md"
    source.write_text("No figures.")
    final = tmp_path / "output/paper"
    bundle(final, source)
    manifest = json.loads((final / "source_manifest.json").read_text())
    manifest.pop("figure_contract_version")
    manifest["artifacts"].pop("figures.jsonl")
    manifest["agent"] = "original-producer"
    (final / "figures.jsonl").unlink()
    (final / "img").rmdir()
    write_json(final / "source_manifest.json", manifest)
    original = {name: (final / name).read_bytes() for name in ("data.jsonl", "original.jsonl", "reasoning.md")}

    def fake(path, *, out_dir, figures_only, **kwargs):
        """The image-only coordinator supplies its inventory and leaves copied data alone."""
        assert figures_only
        (out_dir / "figures.jsonl").write_text("")
        (out_dir / "img").mkdir()
        return success()

    monkeypatch.setattr(runner, "_run_agent", fake)
    monkeypatch.setattr(runner, "prepare_output", lambda path: pytest.fail("backfill normalized data"))
    result = runner.run_one(source, out_dir=tmp_path / "output", timeout=30, budget=None, figures_only=True, agent="test")
    assert result["ok"], result
    for name, content in original.items():
        assert (final / name).read_bytes() == content
    manifest = verify_artifacts(final, source)
    assert manifest["agent"] == "original-producer"
    assert manifest["figure_agent"] == "test"


def test_backfill_rejects_data_changes(tmp_path, monkeypatch):
    """Image work cannot quietly alter structured extraction or its reasoning."""
    source = tmp_path / "paper.md"
    source.write_text("No figures.")
    final = tmp_path / "output/paper"
    bundle(final, source)
    expected = checksum(final / "reasoning.md")

    def fake(path, *, out_dir, **kwargs):
        """Simulate an image agent mistakenly editing the protected evidence summary."""
        (out_dir / "figures.jsonl").write_text("")
        (out_dir / "img").mkdir()
        (out_dir / "reasoning.md").write_text("Unauthorized change")
        return success()

    monkeypatch.setattr(runner, "_run_agent", fake)
    result = runner.run_one(source, out_dir=tmp_path / "output", timeout=30, budget=None,
                            figures_only=True, validation_retries=0)
    assert not result["ok"]
    assert checksum(final / "reasoning.md") == expected


def test_publication_rolls_back_directory_and_files(tmp_path, monkeypatch):
    """A filesystem failure after image replacement restores the complete old bundle."""
    draft, final = tmp_path / "draft", tmp_path / "final"
    for directory, text in ((draft, "new"), (final, "old")):
        (directory / "img").mkdir(parents=True)
        (directory / "img/a.png").write_text(text)
        (directory / "figures.jsonl").write_text(text)
    replace = Path.replace

    def interrupted(path, target):
        """Fail exactly once when publishing the inventory after replacing the image directory."""
        if path == draft / "figures.jsonl" and target == final / "figures.jsonl":
            raise OSError("simulated publication failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="simulated"):
        runner.publish_artifacts(draft, final, ["img", "figures.jsonl"])
    assert (final / "img/a.png").read_text() == "old"
    assert (final / "figures.jsonl").read_text() == "old"
    assert (draft / "img/a.png").read_text() == "new"


@pytest.mark.parametrize("figures_only", [False, True])
def test_claude_enables_image_delegation_without_data_crosscheck(tmp_path, monkeypatch, figures_only):
    """The real CLI command allows native delegation even when data cross-checking is off."""
    import subprocess
    commands = []
    monkeypatch.setattr(runner, "REPO", tmp_path)

    def capture(command, **kwargs):
        """Capture the invocation without launching a paid external backend."""
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps({"result": "done", "total_cost_usd": 0}), "")

    monkeypatch.setattr(runner.subprocess, "run", capture)
    runner._run_agent(tmp_path / "paper.pdf", agent="claude", out_dir=tmp_path / "draft",
                      timeout=10, budget=1, env={}, model=None, effort="high",
                      input_price=None, cached_input_price=None, output_price=None,
                      subagent=False, figures_only=figures_only)
    command = commands[0]
    assert "Agent" in command and "Task" in command
    assert "image subagent" in command[2]
    assert "docs/figure_extraction.md" in command[2]
    assert "Do not spawn subagents" not in command[2]
