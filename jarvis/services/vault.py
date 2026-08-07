import asyncio
import re
import urllib.parse

import requests
import urllib3

from jarvis import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
TIMEOUT = 5


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


def read_links(path: str) -> list[str]:
    """Read a note's raw markdown and return the list of wikilink targets."""
    base = _base_url()
    url = base + "/vault/" + _encode_path(path)
    r = requests.get(url, headers=_headers(accept="text/markdown"), timeout=TIMEOUT, verify=_verify())
    r.raise_for_status()
    text = r.text
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(text)]


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
    if not _api_key():
        await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": "no API key configured"})
        return

    while True:
        try:
            files = await asyncio.to_thread(list_files)
            links: dict[str, list[str]] = {}
            for f in files:
                links[f] = await asyncio.to_thread(read_links, f)

            graph = build_graph(files, links)
            await hub.broadcast(graph)

            top_level = sorted({f.split("/", 1)[0] for f in files if "/" in f})
            work_notes = [f for f in files if f.startswith("03 Work/")]
            last_note = files[-1] if files else None
            await hub.broadcast({
                "type": "vault",
                "projects": top_level,
                "threads": len(work_notes),
                "lastNote": last_note,
            })
        except Exception as e:
            await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": str(e)})

        await asyncio.sleep(interval)
