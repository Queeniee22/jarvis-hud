import asyncio
import logging
import re
import urllib.parse

import requests
import urllib3

from jarvis import config

log = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
TIMEOUT = 5

# Paths seen in the most recent vault listing (set by run() each cycle).
# note_open/note_save in app.py check against this before touching disk --
# a websocket message is untrusted input, and without this a malformed or
# malicious path could read or write outside the notes the graph actually
# knows about.
_known_paths: set[str] = set()


def _base_url() -> str:
    return f"{config.OBSIDIAN_SCHEME}://127.0.0.1:{config.OBSIDIAN_PORT}"


def _api_key() -> str:
    return config.OBSIDIAN_API_KEY or ""


def _verify() -> bool:
    return config.OBSIDIAN_SCHEME != "https"


def _headers(accept: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {_api_key()}"}
    if accept:
        h["Accept"] = accept
    return h


def _encode_path(path: str) -> str:
    return "/".join(urllib.parse.quote(seg) for seg in path.split("/"))


def list_files(dir_path: str = "") -> list[str]:
    """Recursively list all .md files under dir_path (relative to vault root)."""
    base = _base_url()
    url = base + "/vault/" + (_encode_path(dir_path) if dir_path else "")
    r = requests.get(url, headers=_headers(), timeout=TIMEOUT, verify=_verify())
    r.raise_for_status()
    entries = r.json().get("files", [])

    files: list[str] = []
    for entry in entries:
        full = f"{dir_path}{entry}" if dir_path else entry
        if entry.endswith("/"):
            files.extend(list_files(full))
        elif full.endswith(".md"):
            files.append(full)
    return files


def _get_markdown(path: str) -> str:
    """GET a note's raw markdown body. Shared by read_links (which only wants
    the wikilinks out of it) and read_note (which wants the whole thing)."""
    base = _base_url()
    url = base + "/vault/" + _encode_path(path)
    r = requests.get(url, headers=_headers(accept="text/markdown"), timeout=TIMEOUT, verify=_verify())
    r.raise_for_status()
    return r.text


def read_links(path: str) -> list[str]:
    """Read a note's raw markdown and return the list of wikilink targets."""
    text = _get_markdown(path)
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(text)]


def _title(path: str) -> str:
    """'02 Programming/Debug Log.md' -> 'Debug Log'."""
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def read_note_meta(path: str) -> dict:
    """Wikilink targets plus the note's last-modified time, in one request.

    The API's note+json form returns content and `stat` together, so the
    graph pass gets modification times for free rather than paying a second
    round-trip per note just to answer "which note did he touch last".
    """
    base = _base_url()
    url = f"{base}/vault/{_encode_path(path)}"
    r = requests.get(
        url,
        headers=_headers(accept="application/vnd.olrapi.note+json"),
        timeout=TIMEOUT,
        verify=_verify(),
    )
    r.raise_for_status()
    data = r.json()
    text = data.get("content") or ""
    return {
        "links": [m.group(1).strip() for m in WIKILINK_RE.finditer(text)],
        "mtime": (data.get("stat") or {}).get("mtime") or 0,
        # Free here -- the content is already in hand for the wikilinks. Note
        # count alone is too small a number to be worth the big readout, and
        # size in bytes says more about images than about what he has written.
        "words": len(text.split()),
    }


def read_note(path: str) -> str:
    """Read a note's raw markdown, for display/editing in the HUD."""
    return _get_markdown(path)


def write_note(path: str, content: str) -> None:
    """Overwrite a note's full body in the vault. Caller (app.py) is
    responsible for checking is_known_path first -- this function trusts
    whatever path it is given."""
    base = _base_url()
    url = base + "/vault/" + _encode_path(path)
    headers = _headers()
    headers["Content-Type"] = "text/markdown"
    r = requests.put(url, headers=headers, data=content.encode("utf-8"), timeout=TIMEOUT, verify=_verify())
    r.raise_for_status()


def known_paths() -> set[str]:
    """The note paths seen in the most recent vault listing."""
    return set(_known_paths)


def is_known_path(path: str) -> bool:
    """Guard for note_open/note_save: reject anything not in the vault's own
    file list rather than handing an arbitrary path to the REST client.

    Re-lists the vault before rejecting. The listing is a cheap directory
    walk, and it only happens on a miss, but it removes two real ways an
    honest click got refused: clicking during the seconds before the first
    scan finishes, and clicking a note created in Obsidian since the last
    scan. Being wrong here is invisible to the guard's purpose -- a path
    still has to exist in the vault to pass.
    """
    global _known_paths
    if path in _known_paths:
        return True
    try:
        _known_paths = set(list_files())
    except Exception:
        log.warning("vault: could not refresh the file list to check %r", path)
        return False
    return path in _known_paths


def build_graph(files: list[str], links: dict[str, list[str]]) -> dict:
    """Build a {type, nodes, links} graph payload from a file list and a
    path -> [wikilink target] map. Wikilink targets are resolved to a file
    by basename (case-insensitive), falling back to exact path match."""
    by_basename: dict[str, str] = {}
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if name.endswith(".md"):
            name = name[:-3]
        by_basename[name.lower()] = f

    nodes = []
    for f in files:
        name = f.rsplit("/", 1)[-1]
        label = name[:-3] if name.endswith(".md") else name
        group = f.split("/", 1)[0] if "/" in f else "root"
        nodes.append({"id": f, "label": label, "group": group})

    result_links = []
    seen = set()
    for src, targets in links.items():
        for target in targets:
            resolved = None
            if target in files:
                resolved = target
            else:
                target_name = target[:-3] if target.endswith(".md") else target
                resolved = by_basename.get(target_name.lower())
            if resolved is None:
                continue
            key = (src, resolved)
            if key in seen:
                continue
            seen.add(key)
            result_links.append({"s": src, "t": resolved})

    return {"type": "graph", "nodes": nodes, "links": result_links}


async def run(hub, interval: float = 60.0):
    global _known_paths
    if not _api_key():
        await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": "no API key configured"})
        return

    # Report transitions, not every cycle. The hub keeps the last status per
    # service and replays it to new clients, so a repeat adds nothing -- and
    # a failure that is never followed by a recovery would leave every future
    # client being told a healthy vault is offline.
    online: bool | None = None

    while True:
        try:
            files = await asyncio.to_thread(list_files)
            _known_paths = set(files)
            links: dict[str, list[str]] = {}
            mtimes: dict[str, int] = {}
            words = 0
            for f in files:
                meta = await asyncio.to_thread(read_note_meta, f)
                links[f] = meta["links"]
                mtimes[f] = meta["mtime"]
                words += meta.get("words", 0)

            graph = build_graph(files, links)
            await hub.broadcast(graph)

            # Actually the most recently edited note. This used to be
            # files[-1] -- the last path alphabetically -- which looked
            # plausible and was almost always wrong.
            newest = max(mtimes, key=mtimes.get) if mtimes else None
            await hub.broadcast({
                "type": "vault",
                "notes": len(files),
                "links": len(graph["links"]),
                "folders": len({f.split("/", 1)[0] for f in files if "/" in f}),
                "lastNote": _title(newest) if newest else None,
                "lastEditedMs": mtimes.get(newest) if newest else None,
                "words": words,
            })
            if online is not True:
                await hub.broadcast({"type": "status", "service": "vault", "state": "online"})
                online = True
        except Exception as e:
            if online is not False:
                await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": str(e)})
                online = False

        await asyncio.sleep(interval)
