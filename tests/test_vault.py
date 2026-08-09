import asyncio

import pytest
import requests

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


class _FakeResponse:
    """Stands in for requests.Response: records nothing itself, just lets the
    test control status/body/text without a real HTTP call."""

    def __init__(self, text="", ok=True):
        self.text = text
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("500 Server Error")


def test_read_note_gets_markdown_with_accept_header(monkeypatch):
    """read_note must GET /vault/{encoded path} with an Accept: text/markdown
    header (same convention as read_links) and hand back the raw body."""
    calls = []

    def fake_get(url, headers=None, timeout=None, verify=None):
        calls.append((url, headers))
        return _FakeResponse(text="# Hello\n\nsome body")

    monkeypatch.setattr(vault.requests, "get", fake_get)
    monkeypatch.setattr(vault.config, "OBSIDIAN_API_KEY", "test-key")

    result = vault.read_note("01 Preferences/About Mackenzie.md")

    assert result == "# Hello\n\nsome body"
    assert len(calls) == 1
    url, headers = calls[0]
    assert url.endswith("/vault/01%20Preferences/About%20Mackenzie.md")
    assert headers["Accept"] == "text/markdown"
    assert headers["Authorization"] == "Bearer test-key"


def test_write_note_puts_markdown_content_type(monkeypatch):
    """write_note must PUT the content back with Content-Type: text/markdown,
    to the same encoded-path URL convention as the read side."""
    calls = []

    def fake_put(url, headers=None, data=None, timeout=None, verify=None):
        calls.append((url, headers, data))
        return _FakeResponse()

    monkeypatch.setattr(vault.requests, "put", fake_put)
    monkeypatch.setattr(vault.config, "OBSIDIAN_API_KEY", "test-key")

    vault.write_note("01 Preferences/About Mackenzie.md", "new content")

    assert len(calls) == 1
    url, headers, data = calls[0]
    assert url.endswith("/vault/01%20Preferences/About%20Mackenzie.md")
    assert headers["Content-Type"] == "text/markdown"
    assert headers["Authorization"] == "Bearer test-key"
    assert data == b"new content"


def test_write_note_raises_on_non_2xx(monkeypatch):
    """A failed PUT must surface as an exception -- app.py relies on this to
    turn a bad write into a note_error instead of a silent no-op."""
    monkeypatch.setattr(vault.requests, "put", lambda *a, **k: _FakeResponse(ok=False))
    monkeypatch.setattr(vault.config, "OBSIDIAN_API_KEY", "test-key")

    with pytest.raises(requests.HTTPError):
        vault.write_note("A.md", "content")


def test_is_known_path_guard(monkeypatch):
    """The websocket handler trusts this before ever touching disk: a path
    that never showed up in a vault listing must be rejected."""
    monkeypatch.setattr(vault, "_known_paths", {"A.md", "01 Preferences/About Mackenzie.md"})

    assert vault.is_known_path("A.md") is True
    assert vault.is_known_path("../../etc/passwd") is False
    assert vault.is_known_path("B.md") is False


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
    # run() reads links and mtime together now, in one request per note.
    monkeypatch.setattr(vault, "read_note_meta", lambda path: {"links": [], "mtime": 0})
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


def test_is_known_path_refreshes_for_a_note_added_since_the_last_scan(monkeypatch):
    """A note created in Obsidian after the last scan -- or a click during
    the seconds before the first scan -- must not be refused."""
    from jarvis.services import vault

    monkeypatch.setattr(vault, "_known_paths", {"old.md"})
    monkeypatch.setattr(vault, "list_files", lambda *a, **k: ["old.md", "brand new.md"])

    assert vault.is_known_path("brand new.md") is True
    # the refreshed listing is retained, so the next check needs no re-list
    monkeypatch.setattr(vault, "list_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-list")))
    assert vault.is_known_path("brand new.md") is True


def test_is_known_path_still_rejects_paths_not_in_the_vault(monkeypatch):
    """The refresh must not weaken the guard."""
    from jarvis.services import vault

    monkeypatch.setattr(vault, "_known_paths", set())
    monkeypatch.setattr(vault, "list_files", lambda *a, **k: ["real.md"])
    assert vault.is_known_path("../../etc/passwd") is False
    assert vault.is_known_path("not a note.md") is False


def test_is_known_path_rejects_when_the_vault_is_unreachable(monkeypatch):
    """Obsidian being down must deny, not raise into the websocket handler."""
    from jarvis.services import vault

    monkeypatch.setattr(vault, "_known_paths", set())
    def boom(*a, **k):
        raise ConnectionError("vault down")
    monkeypatch.setattr(vault, "list_files", boom)
    assert vault.is_known_path("anything.md") is False


def test_read_note_meta_returns_links_and_mtime(monkeypatch):
    """One request must yield both, or the graph pass pays a second
    round-trip per note just to answer 'what did he edit last'."""
    from jarvis.services import vault

    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "content": "see [[Debug Log]] and [[Projects]]",
                "stat": {"mtime": 1786040005194, "ctime": 1, "size": 10},
            }

    def fake_get(url, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["accept"] = (headers or {}).get("Accept")
        return FakeResp()

    monkeypatch.setattr(vault.requests, "get", fake_get)
    meta = vault.read_note_meta("02 Programming/Debug Log.md")

    assert meta["links"] == ["Debug Log", "Projects"]
    assert meta["mtime"] == 1786040005194
    assert captured["accept"] == "application/vnd.olrapi.note+json"
    assert "%20" in captured["url"], "spaces in vault paths must be encoded"


def test_read_note_meta_survives_a_note_with_no_stat(monkeypatch):
    from jarvis.services import vault

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"content": "no links here"}

    monkeypatch.setattr(vault.requests, "get", lambda *a, **k: FakeResp())
    meta = vault.read_note_meta("A.md")
    assert meta["links"] == []
    assert meta["mtime"] == 0, "a note with no stat must not break the scan"
    assert meta["words"] == 3, "word count comes from the content, not from stat"


async def test_vault_panel_reports_the_most_recently_edited_note(monkeypatch):
    """It used to report files[-1] -- the last path alphabetically -- which
    looked plausible and was almost always the wrong note."""
    from jarvis.services import vault

    files = ["00 Index/Aardvark.md", "99 Zebra.md", "05 Daily/Today.md"]
    mtimes = {"00 Index/Aardvark.md": 100, "99 Zebra.md": 200, "05 Daily/Today.md": 999}

    monkeypatch.setattr(vault, "list_files", lambda *a, **k: files)
    monkeypatch.setattr(vault, "read_note_meta",
                        lambda path: {"links": [], "mtime": mtimes[path]})
    monkeypatch.setattr(vault.config, "OBSIDIAN_API_KEY", "test-key")

    class Hub:
        def __init__(self): self.msgs = []
        async def broadcast(self, m): self.msgs.append(m)

    hub = Hub()
    task = asyncio.create_task(vault.run(hub, interval=3600))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(m.get("type") == "vault" for m in hub.msgs):
            break
    task.cancel()

    payload = [m for m in hub.msgs if m.get("type") == "vault"][0]
    assert payload["lastNote"] == "Today", "must be newest by mtime, not last alphabetically"
    assert payload["notes"] == 3
    assert payload["lastEditedMs"] == 999
