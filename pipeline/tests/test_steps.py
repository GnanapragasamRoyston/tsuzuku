"""Règles de fraîcheur des étapes."""

import os

from tsuzuku_pipeline.steps import Step, is_fresh


def _counting_step(tmp_path, config):
    calls = []

    def build(spark, settings):
        calls.append(1)
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        (out / "_SUCCESS").write_text("")

    step = Step(
        "demo",
        inputs=lambda s: [],
        outputs=lambda s: [tmp_path / "out"],
        build=build,
        config=config,
        stamp_dir=lambda s: tmp_path / ".stamps",
    )
    return step, calls


def test_config_change_makes_step_stale(tmp_path):
    settings = {"t": {"ratio": 0.25}}
    step, calls = _counting_step(tmp_path, lambda s: s["t"])
    step.run(None, settings, force=False)
    step.run(None, settings, force=False)
    assert len(calls) == 1  # à jour : sautée

    settings["t"]["ratio"] = 0.2  # seuil modifié dans settings.yaml
    step.run(None, settings, force=False)
    assert len(calls) == 2


def test_failed_build_leaves_no_stamp(tmp_path):
    def boom(spark, settings):
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / "_SUCCESS").write_text("")
        raise RuntimeError("contrôle de cohérence en échec")

    step = Step("demo", lambda s: [], lambda s: [tmp_path / "out"], boom,
                config=lambda s: {"a": 1}, stamp_dir=lambda s: tmp_path / ".stamps")  # fmt: skip
    try:
        step.run(None, {}, force=False)
    except RuntimeError:
        pass
    # Les sorties existent, mais sans tampon l'étape reste périmée : elle sera refaite.
    assert step.is_up_to_date({}) is False


def _touch(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, ns=(mtime, mtime))


def test_no_outputs_is_never_fresh(tmp_path):
    assert is_fresh([], [tmp_path / "in.csv"]) is False


def test_missing_success_marker_is_not_fresh(tmp_path):
    (tmp_path / "out").mkdir()
    assert is_fresh([tmp_path / "out"], []) is False


def test_output_older_than_input_is_stale(tmp_path):
    _touch(tmp_path / "out" / "_SUCCESS", 1_000)
    _touch(tmp_path / "in.csv", 2_000)
    assert is_fresh([tmp_path / "out"], [tmp_path / "in.csv"]) is False


def test_output_newer_than_inputs_is_fresh(tmp_path):
    _touch(tmp_path / "out" / "_SUCCESS", 3_000)
    _touch(tmp_path / "in.csv", 2_000)
    assert is_fresh([tmp_path / "out"], [tmp_path / "in.csv", tmp_path / "absent.csv"]) is True
