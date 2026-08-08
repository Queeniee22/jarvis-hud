import asyncio

import pytest

from jarvis.hub import ConnectionHub
from jarvis.services import vault
from jarvis.services.vault import build_graph

def test_build_graph_nodes_and_links():
    files = ["A.md", "B.md", "C.md"]
    links = {"A.md": ["B.md"], "B.md": ["C.md"], "C.md": []}
    g = build_graph(files, links)
    assert g["type"] == "graph"
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"A.md", "B.md", "C.md"}
    assert {"s": "A.md", "t": "B.md"} in g["links"]
    assert {"s": "B.md", "t": "C.md"} in g["links"]

def test_build_graph_resolves_wikilink_by_basename():
    files = ["00 Index/Jarvis Home.md", "01 Preferences/About Mackenzie.md"]
    links = {"00 Index/Jarvis Home.md": ["About Mackenzie"], "01 Preferences/About Mackenzie.md": []}
    g = build_graph(files, links)
    assert {"s": "00 Index/Jarvis Home.md", "t": "01 Preferences/About Mackenzie.md"} in g["links"]


async def _run_cycles(hub, monkeypatch, outcomes, interval=0.01):
    """Drive vault.run through one outcome per cycle, then stop it.

    Each outcome is either an exception to raise or a file list to return.
    """
    calls = {"n": 0}

    def fake_list_files(dir_path=""):
        i = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        outcome = outcomes[i]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(vault, "list_files", fake_list_files)
    monkeypatch.setattr(vault, "read_links", lambda path: [])
    monkeypatch.setattr(vault.config, "OBSIDIAN_API_KEY", "test-key")

    task = asyncio.create_task(vault.run(hub, interval=interval))
    while calls["n"] < len(outcomes):
        await asyncio.sleep(0.01)
    await asyncio.sleep(interval * 2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.fixture
async def hub():
    h = ConnectionHub()
    yield h
    await h.close()


async def test_recovery_supersedes_the_cached_offline_status(hub, monkeypatch):
    """A client connecting after the vault recovers must not be told it is
    offline. The hub caches the last status per service forever, so a failed
    cycle that is never superseded misreports a healthy vault indefinitely."""
    await _run_cycles(hub, monkeypatch, [RuntimeError("obsidian closed"), ["A.md"]])

    statuses = [m for m in hub.snapshot()
                if m["type"] == "status" and m.get("service") == "vault"]
    assert statuses, "no vault status cached at all"
    assert statuses[-1]["state"] == "online", (
        f"stale offline status survives recovery: {statuses[-1]}")


async def test_repeated_failures_do_not_spam_identical_statuses(hub, monkeypatch):
    """Offline is a state, not an event -- the hub already replays it."""
    sent = []

    class RecordingWS:
        async def send_json(self, obj): sent.append(obj)

    hub.add(RecordingWS())
    await _run_cycles(hub, monkeypatch, [RuntimeError("down"), RuntimeError("down"), RuntimeError("down")])
    await hub.drain()

    offline = [m for m in sent
               if m["type"] == "status" and m.get("service") == "vault"]
    assert len(offline) == 1, f"one transition, not one per cycle: {offline}"
