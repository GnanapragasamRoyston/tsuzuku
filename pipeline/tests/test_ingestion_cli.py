"""Chaînes de production (Cloud Run Job, ADR 014) : mêmes étapes que les DAG, arrêt au 1er échec."""

import datetime as dt
import json

import pytest

from tsuzuku_pipeline.ingestion import cli

DAY = dt.date(2026, 11, 23)


def test_chains_mirror_the_airflow_dags():
    # Mêmes noms de tâches, même ordre que pipeline/dags (test_dags.py vérifie le côté Airflow).
    assert [n for n, _ in cli.CHAINS["jikan-daily"]] == [
        "collect", "fetch_stats", "load", "quality_check"]  # fmt: skip
    assert [n for n, _ in cli.CHAINS["anilist-weekly"]] == [
        "fetch_pages", "load", "quality_check", "anime_covers"]  # fmt: skip


def test_run_chain_logs_each_step_and_stops_at_the_first_failure(monkeypatch, capsys):
    calls = []

    def ok(name):
        def step(settings, day):
            calls.append(name)
            return {"ok": name}

        return step

    def boom(settings, day):
        calls.append("boom")
        raise RuntimeError("Contrôle qualité en échec")

    monkeypatch.setitem(cli.CHAINS, "test", (("a", ok("a")), ("b", boom), ("c", ok("c"))))
    with pytest.raises(RuntimeError):
        cli.run_chain("test", {}, DAY)
    assert calls == ["a", "boom"]  # « c » ne tourne pas après l'échec
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert logged == [{"task": "test", "step": "a", "result": {"ok": "a"}}]
