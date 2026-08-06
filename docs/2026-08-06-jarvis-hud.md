# Jarvis HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pastel-pixel, voice-enabled "Jarvis" HUD that runs fullscreen in a browser, backed by a local Python server wiring live system vitals, a Claude-Code chat brain, open-mic speech (faster-whisper in / ElevenLabs out), the user's Obsidian vault graph, and Google Calendar.

**Architecture:** A FastAPI backend (`python -m jarvis` / `run.py`) serves a static vanilla-JS HUD and holds one WebSocket per client. Backend "services" (vitals, brain, ears, voice, vault, calendar) each run independently and push typed JSON messages over the socket; the frontend renders panels + a Canvas particle-sphere core that reacts to TTS amplitude, and a pink mic waveform that reacts to mic amplitude. Every service degrades to an "offline" state without taking down the HUD.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, websockets, psutil, faster-whisper, sounddevice, requests (ElevenLabs), google-api-python-client + google-auth-oauthlib, an Obsidian Local REST API client; frontend is vanilla HTML/CSS/JS + Canvas 2D, pixel fonts bundled locally. Tests: pytest.

**Repo:** `C:\Users\Mackenzie\jarvis-hud` (separate from the Obsidian vault). The approved static mockup lives at the scratchpad path and is the visual source of truth for Phase 1.

**Message protocol (WebSocket, JSON, one object per message):**
- Server→client: `{"type":"vitals","cpu":42,"ram":38,"disk":12}` · `{"type":"chat","role":"jarvis","delta":"...","done":false}` · `{"type":"mic","level":0.0-1.0,"muted":false}` · `{"type":"speak","level":0.0-1.0,"active":true}` · `{"type":"vault","projects":[...],"threads":3,"lastNote":"..."}` · `{"type":"graph","nodes":[{"id","label","group"}],"links":[{"s","t"}]}` · `{"type":"calendar","events":[{"time","title"}]}` · `{"type":"status","service":"voice","state":"offline","detail":"no ELEVENLABS_API_KEY"}`
- Client→server: `{"type":"say","text":"..."}` (user chat) · `{"type":"mute","value":true}` · `{"type":"tab","value":"graph"}`

---

## File Structure

```
jarvis-hud/
  run.py                     # entrypoint: uvicorn jarvis.app:app
  pyproject.toml             # deps + pytest config
  .gitignore                 # .env, .venv, models/, __pycache__
  .env.example               # ELEVENLABS_API_KEY=, VOICE_ID=, OBSIDIAN_API_KEY=, OBSIDIAN_PORT=
  jarvis/
    __init__.py
    app.py                   # FastAPI app, static mount, /ws endpoint, hub wiring
    hub.py                   # ConnectionHub: broadcast() + per-client send queue
    config.py                # env loading, ports, paths
    services/
      __init__.py
      vitals.py              # psutil sampler → vitals messages
      brain.py               # Claude Code CLI subprocess streamer
      ears.py                # faster-whisper mic loop + amplitude
      voice.py               # ElevenLabs TTS + output amplitude
      vault.py               # Obsidian REST client → vault + graph
      calendar.py            # Google Calendar OAuth → today's events
  static/
    index.html               # HUD markup (from approved mockup)
    css/hud.css              # extracted styles
    js/hud.js                # WS client, panel binding, tab switch
    js/core.js               # particle-sphere Canvas render (+ speak reactivity)
    js/graph.js              # force-directed vault graph Canvas render
    js/wave.js               # pink mic waveform bars (+ mic reactivity, mute)
    fonts/                   # PressStart2P + PixelifySans .woff2 (bundled)
  tests/
    test_hub.py
    test_vitals.py
    test_brain.py
    test_vault.py
    test_calendar.py
    test_protocol.py
```

Split by responsibility: each service owns one integration and one message type; frontend render modules are separated so the Canvas code (core/graph/wave) stays isolated from the WS/panel glue.

---

## Phase 0 — Repo scaffold

### Task 0: Project skeleton, deps, test harness

**Files:**
- Create: `C:\Users\Mackenzie\jarvis-hud\pyproject.toml`
- Create: `C:\Users\Mackenzie\jarvis-hud\.gitignore`
- Create: `C:\Users\Mackenzie\jarvis-hud\.env.example`
- Create: `C:\Users\Mackenzie\jarvis-hud\jarvis\__init__.py`
- Create: `C:\Users\Mackenzie\jarvis-hud\run.py`
- Create: `C:\Users\Mackenzie\jarvis-hud\tests\test_smoke.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "jarvis-hud"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "psutil>=5.9",
  "python-dotenv>=1.0",
  "requests>=2.31",
  "sounddevice>=0.4",
  "numpy>=1.26",
  "faster-whisper>=1.0",
  "google-api-python-client>=2.0",
  "google-auth-oauthlib>=1.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
.env
.venv/
__pycache__/
*.pyc
models/
token.json
credentials.json
```

- [ ] **Step 3: Write `.env.example`**

```dotenv
ELEVENLABS_API_KEY=
VOICE_ID=
OBSIDIAN_API_KEY=
OBSIDIAN_PORT=27126
GOOGLE_CALENDAR_ID=primary
```

- [ ] **Step 4: Write `jarvis/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Write `run.py`**

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run("jarvis.app:app", host="127.0.0.1", port=8770, reload=False)
```

- [ ] **Step 6: Write `tests/test_smoke.py`**

```python
import jarvis

def test_version():
    assert jarvis.__version__ == "0.1.0"
```

- [ ] **Step 7: Create venv, install, run test**

```bash
cd "C:/Users/Mackenzie/jarvis-hud"
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
```
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git init && git add -A && git commit -m "chore: scaffold jarvis-hud repo"
```

---

## Phase 1 — Backend server + HUD shell (mocked data)

### Task 1: ConnectionHub

**Files:**
- Create: `jarvis/hub.py`
- Test: `tests/test_hub.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import pytest
from jarvis.hub import ConnectionHub

class FakeWS:
    def __init__(self): self.sent = []
    async def send_json(self, obj): self.sent.append(obj)

@pytest.mark.asyncio
async def test_broadcast_reaches_all_clients():
    hub = ConnectionHub()
    a, b = FakeWS(), FakeWS()
    hub.add(a); hub.add(b)
    await hub.broadcast({"type": "vitals", "cpu": 10})
    assert a.sent == [{"type": "vitals", "cpu": 10}]
    assert b.sent == [{"type": "vitals", "cpu": 10}]

@pytest.mark.asyncio
async def test_remove_stops_delivery():
    hub = ConnectionHub()
    a = FakeWS(); hub.add(a); hub.remove(a)
    await hub.broadcast({"type": "x"})
    assert a.sent == []
```

- [ ] **Step 2: Add asyncio marker + run to verify fail**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`: `asyncio_mode = "auto"` and add `pytest-asyncio>=0.23` to dev deps, reinstall.
Run: `.venv/Scripts/python -m pytest tests/test_hub.py -q`
Expected: FAIL (no module `jarvis.hub`).

- [ ] **Step 3: Implement `jarvis/hub.py`**

```python
import asyncio

class ConnectionHub:
    def __init__(self):
        self._clients = set()
        self._lock = asyncio.Lock()

    def add(self, ws): self._clients.add(ws)
    def remove(self, ws): self._clients.discard(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_hub.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: connection hub with broadcast"
```

### Task 2: FastAPI app, static serving, /ws endpoint

**Files:**
- Create: `jarvis/config.py`
- Create: `jarvis/app.py`
- Test: `tests/test_protocol.py`

- [ ] **Step 1: Write `jarvis/config.py`**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = 8770

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("VOICE_ID", "")
OBSIDIAN_API_KEY = os.getenv("OBSIDIAN_API_KEY", "")
OBSIDIAN_PORT = int(os.getenv("OBSIDIAN_PORT", "27126"))
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
```

- [ ] **Step 2: Write the failing test**

```python
from fastapi.testclient import TestClient
from jarvis.app import app

def test_index_served():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "JARVIS" in r.text

def test_ws_accepts_and_echoes_status():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "hello"
```

- [ ] **Step 3: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_protocol.py -q`
Expected: FAIL (no `jarvis.app`).

- [ ] **Step 4: Implement `jarvis/app.py`**

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jarvis import config
from jarvis.hub import ConnectionHub

app = FastAPI()
hub = ConnectionHub()

app.mount("/css", StaticFiles(directory=config.STATIC / "css"), name="css")
app.mount("/js", StaticFiles(directory=config.STATIC / "js"), name="js")
app.mount("/fonts", StaticFiles(directory=config.STATIC / "fonts"), name="fonts")

@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")

@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    hub.add(sock)
    await sock.send_json({"type": "hello", "app": "jarvis"})
    try:
        while True:
            await sock.receive_json()  # client messages handled in later phases
    except WebSocketDisconnect:
        hub.remove(sock)
```

- [ ] **Step 5: Create placeholder static dirs so mounts resolve**

```bash
mkdir -p static/css static/js static/fonts
printf '<!doctype html><title>JARVIS</title><h1>JARVIS</h1>' > static/index.html
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_protocol.py -q`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: fastapi app with static + ws endpoint"
```

### Task 3: Port the approved mockup into split static files

**Files:**
- Modify: `static/index.html` (replace placeholder with the approved mockup markup)
- Create: `static/css/hud.css`
- Create: `static/js/core.js`, `static/js/graph.js`, `static/js/wave.js`, `static/js/hud.js`
- Create: `static/fonts/PressStart2P.woff2`, `static/fonts/PixelifySans.woff2`

- [ ] **Step 1: Copy the approved mockup HTML in as `static/index.html`**

Source file: `C:\Users\MACKEN~1\AppData\Local\Temp\claude\C--Users-Mackenzie-Jarvis\14b99379-b62f-4ae6-a93f-28adc4a79190\scratchpad\jarvis-mockup.html`. Copy its `<body>` markup verbatim into `index.html`.

- [ ] **Step 2: Bundle fonts locally (no CDN)**

```bash
cd "C:/Users/Mackenzie/jarvis-hud/static/fonts"
curl -L -o PressStart2P.woff2 "https://fonts.gstatic.com/s/pressstart2p/v15/e3t4euO8T-267oIAQAu6jDQyK3nVivM.woff2"
curl -L -o PixelifySans.woff2 "https://fonts.gstatic.com/s/pixelifysans/v1/CHy2V-3HFUT7aC4iv1TxGDR9DHEserHN25py2Tfjm7WGnkP.woff2"
```
Replace the `<link>` Google Fonts tag in `index.html` with an `@font-face` block in `hud.css`:

```css
@font-face{font-family:"Press Start 2P";src:url("/fonts/PressStart2P.woff2") format("woff2");}
@font-face{font-family:"Pixelify Sans";src:url("/fonts/PixelifySans.woff2") format("woff2");}
```

- [ ] **Step 3: Extract `<style>` → `static/css/hud.css`; link it**

Move the mockup's entire `<style>` block into `hud.css` (prepend the `@font-face` block). In `index.html` add `<link rel="stylesheet" href="/css/hud.css">` and delete the inline `<style>`.

- [ ] **Step 4: Split the mockup `<script>` into modules**

- `core.js`: the particle-sphere setup + its branch of `frame()` (export `renderCore(speakLevel)` and `initCore()`).
- `graph.js`: node/link generation + graph branch (export `renderGraph(data)` and `initGraph()`); for now keep the mock node generator as a fallback used only when no `graph` message has arrived.
- `wave.js`: bar creation + `setMic(level, muted)` that sets bar heights (drop the random mock once real `mic` messages arrive).
- `hud.js`: clock tick, tab switch, and a single `requestAnimationFrame` loop that calls `renderCore(state.speak)` or `renderGraph(state.graph)` based on active tab. Load with `<script src="/js/core.js"></script>` … then `hud.js` last.

- [ ] **Step 5: Manual verify in browser**

```bash
.venv/Scripts/python run.py
```
Open `http://127.0.0.1:8770`, press F11. Confirm: dark core sphere spins, tabs switch to graph, pink bars animate, clock shows 12-hour AM/PM. (No live data yet — mock visuals only.)

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: port approved pastel HUD shell into split static files"
```

### Task 4: WS client wiring in `hud.js` (state + dispatch)

**Files:**
- Modify: `static/js/hud.js`

- [ ] **Step 1: Add a WS client and central state**

```javascript
const state = { speak:0, mic:{level:0,muted:false}, graph:null, vitals:null };
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === "vitals") applyVitals(m);
  else if (m.type === "mic") { state.mic = m; setMic(m.level, m.muted); }
  else if (m.type === "speak") state.speak = m.active ? m.level : 0;
  else if (m.type === "chat") applyChat(m);
  else if (m.type === "vault") applyVault(m);
  else if (m.type === "graph") state.graph = m;
  else if (m.type === "calendar") applyCalendar(m);
  else if (m.type === "status") applyStatus(m);
};
function send(obj){ if (ws.readyState===1) ws.send(JSON.stringify(obj)); }
```

- [ ] **Step 2: Implement `applyVitals` binding to the existing bar elements**

```javascript
function applyVitals(m){
  document.querySelector(".f1").style.width = m.cpu + "%";
  document.querySelector(".f2").style.width = m.ram + "%";
  document.querySelector(".f3").style.width = m.disk + "%";
  document.querySelectorAll(".pct")[0].textContent = m.cpu + "%";
  document.querySelectorAll(".pct")[1].textContent = m.ram + "%";
  document.querySelectorAll(".pct")[2].textContent = m.disk + "%";
}
```

- [ ] **Step 3: Stub the remaining `apply*` handlers**

Define `applyChat`, `applyVault`, `applyCalendar`, `applyStatus` as no-ops now; they get bodies in their phases. `setMic` and graph rendering already exist from Task 3.

- [ ] **Step 4: Manual verify no console errors**

Reload the page; confirm the socket connects (Network → WS shows the `hello` frame) and no JS errors.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: websocket client + state dispatch in HUD"
```

---

## Phase 2 — Live system vitals

### Task 5: Vitals sampler

**Files:**
- Create: `jarvis/services/__init__.py`, `jarvis/services/vitals.py`
- Modify: `jarvis/app.py`
- Test: `tests/test_vitals.py`

- [ ] **Step 1: Write the failing test**

```python
from jarvis.services.vitals import sample

def test_sample_shape(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 42.4)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("M", (), {"percent": 38.6})())
    monkeypatch.setattr(psutil, "disk_usage", lambda p: type("D", (), {"percent": 12.9})())
    s = sample()
    assert s == {"type": "vitals", "cpu": 42, "ram": 39, "disk": 13}
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_vitals.py -q`
Expected: FAIL (no module).

- [ ] **Step 3: Implement `jarvis/services/vitals.py`**

```python
import asyncio
import psutil

def sample() -> dict:
    return {
        "type": "vitals",
        "cpu": round(psutil.cpu_percent()),
        "ram": round(psutil.virtual_memory().percent),
        "disk": round(psutil.disk_usage("C:\\").percent),
    }

async def run(hub, interval: float = 2.0):
    while True:
        await hub.broadcast(sample())
        await asyncio.sleep(interval)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_vitals.py -q`
Expected: 1 passed.

- [ ] **Step 5: Start the sampler on app startup**

In `jarvis/app.py` add:

```python
import asyncio
from jarvis.services import vitals

@app.on_event("startup")
async def _startup():
    asyncio.create_task(vitals.run(hub))
```

- [ ] **Step 6: Manual verify**

Run `run.py`, open HUD — CPU/RAM/DISK bars now move with real usage every 2s.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: live system vitals over websocket"
```

---

## Phase 3 — Chat brain via Claude Code CLI

### Task 6: Brain streamer

**Files:**
- Create: `jarvis/services/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write the failing test (parse stream-json lines)**

```python
from jarvis.services.brain import parse_stream_line

def test_parse_assistant_text_delta():
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}'
    assert parse_stream_line(line) == "hi"

def test_parse_non_text_returns_none():
    assert parse_stream_line('{"type":"system","subtype":"init"}') is None

def test_parse_garbage_returns_none():
    assert parse_stream_line("not json") is None
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `jarvis/services/brain.py`**

```python
import asyncio
import json

SYSTEM_PROMPT = (
    "You are Jarvis, Mackenzie's cute, terse personal assistant. "
    "Warm, direct, a little playful. Short answers; reasoning on request."
)

def parse_stream_line(line: str):
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if obj.get("type") != "assistant":
        return None
    parts = obj.get("message", {}).get("content", [])
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text or None

async def ask(hub, text: str):
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", text,
        "--append-system-prompt", SYSTEM_PROMPT,
        "--output-format", "stream-json", "--verbose",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async for raw in proc.stdout:
        delta = parse_stream_line(raw.decode("utf-8", "ignore").strip())
        if delta:
            await hub.broadcast({"type": "chat", "role": "jarvis", "delta": delta, "done": False})
    await proc.wait()
    await hub.broadcast({"type": "chat", "role": "jarvis", "delta": "", "done": True})
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_brain.py -q`
Expected: 3 passed.

- [ ] **Step 5: Route client `say` messages to the brain**

In `jarvis/app.py` `/ws` receive loop, replace the discard with:

```python
from jarvis.services import brain, voice
msg = await sock.receive_json()
if msg.get("type") == "say":
    text = msg.get("text", "").strip()
    if text:
        await hub.broadcast({"type": "chat", "role": "you", "delta": text, "done": True})
        asyncio.create_task(brain.ask(hub, text))
elif msg.get("type") == "mute":
    ears.set_muted(bool(msg.get("value")))
```

(`ears`/`voice` imports are used by later phases; add them now to avoid a second edit.)

- [ ] **Step 6: Frontend — send input + render streamed chat**

In `hud.js`: make the `.prompt` accept typed text (add a real `<input>` or contenteditable), send `{type:"say",text}` on Enter, append `you` line immediately, and implement `applyChat` to append/stream `jarvis` deltas into the `.chat` panel.

- [ ] **Step 7: Manual verify**

Run HUD, type "hi jarvis" → streamed reply appears in the chat panel.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: chat brain via claude code cli streaming"
```

---

## Phase 4 — Open-mic ears + mute + waveform

### Task 7: Ears (faster-whisper) with amplitude + mute

**Files:**
- Create: `jarvis/services/ears.py`
- Modify: `jarvis/app.py` (startup task), `static/js/wave.js`, `static/js/hud.js`, `static/index.html` (mute button)
- Test: `tests/test_ears.py`

- [ ] **Step 1: Write the failing test (mute state machine, no audio hardware)**

```python
from jarvis.services import ears

def test_mute_toggle_default_unmuted():
    ears._muted = False
    assert ears.is_muted() is False
    ears.set_muted(True)
    assert ears.is_muted() is True

def test_rms_amplitude_normalized():
    import numpy as np
    block = (np.ones(1600, dtype="float32") * 0.5)
    lvl = ears.rms_level(block)
    assert 0.0 <= lvl <= 1.0 and lvl > 0.4
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_ears.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `jarvis/services/ears.py`**

```python
import asyncio
import numpy as np

_muted = False
def is_muted() -> bool: return _muted
def set_muted(v: bool):
    global _muted; _muted = v

def rms_level(block) -> float:
    rms = float(np.sqrt(np.mean(np.square(block))))
    return max(0.0, min(1.0, rms * 3.0))

async def run(hub):
    try:
        import sounddevice as sd
        from faster_whisper import WhisperModel
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "ears", "state": "offline", "detail": str(e)})
        return
    model = WhisperModel("small", device="cpu", compute_type="int8")
    loop = asyncio.get_event_loop()
    q = asyncio.Queue()
    def cb(indata, frames, t, status):
        lvl = 0.0 if _muted else rms_level(indata[:, 0])
        loop.call_soon_threadsafe(hub_broadcast_nowait, hub, {"type": "mic", "level": lvl, "muted": _muted})
        if not _muted:
            loop.call_soon_threadsafe(q.put_nowait, indata.copy())
    with sd.InputStream(channels=1, samplerate=16000, blocksize=1600, callback=cb):
        buffer = []
        while True:
            block = await q.get()
            buffer.append(block)
            if len(buffer) >= 20:  # ~2s
                audio = np.concatenate(buffer)[:, 0]
                buffer = []
                segments, _ = model.transcribe(audio, language="en")
                text = " ".join(s.text for s in segments).strip()
                if text:
                    await hub.broadcast({"type": "chat", "role": "you", "delta": text, "done": True})
                    from jarvis.services import brain
                    asyncio.create_task(brain.ask(hub, text))

def hub_broadcast_nowait(hub, msg):
    asyncio.create_task(hub.broadcast(msg))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_ears.py -q`
Expected: 2 passed.

- [ ] **Step 5: Start ears on startup + add mute button**

`app.py` startup: `asyncio.create_task(ears.run(hub))`.
`index.html` Voice panel: add `<button id="muteBtn">MUTE</button>`.
`hud.js`: `muteBtn.onclick = () => { const m=!state.mic.muted; send({type:"mute",value:m}); }`.
`wave.js` `setMic(level,muted)`: when muted, flatten bars to min height and gray them (`filter:grayscale(1)`), and turn the `.micdot` gray.

- [ ] **Step 6: Manual verify**

Run HUD; speak → pink bars react + transcript posts to chat + Jarvis replies. Click MUTE → bars flatten/gray, speaking stops being transcribed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: open-mic ears with amplitude, mute, transcription"
```

---

## Phase 5 — Voice out + sphere reactivity

### Task 8: ElevenLabs TTS with output amplitude

**Files:**
- Create: `jarvis/services/voice.py`
- Modify: `jarvis/services/brain.py` (speak completed replies), `jarvis/app.py`
- Test: `tests/test_voice.py`

- [ ] **Step 1: Write the failing test (offline when no key; amplitude framing)**

```python
from jarvis.services import voice

def test_offline_without_key(monkeypatch):
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "")
    assert voice.available() is False

def test_available_with_key(monkeypatch):
    monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "abc")
    monkeypatch.setattr(voice.config, "VOICE_ID", "xyz")
    assert voice.available() is True
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_voice.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `jarvis/services/voice.py`**

```python
import asyncio
import io
import numpy as np
import requests
from jarvis import config

def available() -> bool:
    return bool(config.ELEVENLABS_API_KEY and config.VOICE_ID)

def _fetch_pcm(text: str) -> np.ndarray:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.VOICE_ID}"
    r = requests.post(url,
        headers={"xi-api-key": config.ELEVENLABS_API_KEY, "accept": "audio/pcm"},
        params={"output_format": "pcm_16000"},
        json={"text": text, "model_id": "eleven_turbo_v2_5"}, timeout=30)
    r.raise_for_status()
    return np.frombuffer(r.content, dtype=np.int16).astype("float32") / 32768.0

async def speak(hub, text: str):
    if not available():
        await hub.broadcast({"type": "status", "service": "voice", "state": "offline",
                             "detail": "no ELEVENLABS_API_KEY/VOICE_ID"})
        return
    try:
        pcm = await asyncio.to_thread(_fetch_pcm, text)
    except Exception as e:
        await hub.broadcast({"type": "status", "service": "voice", "state": "error", "detail": str(e)})
        return
    import sounddevice as sd
    sd.play(pcm, 16000)
    step = 1600  # 0.1s frames
    for i in range(0, len(pcm), step):
        frame = pcm[i:i+step]
        lvl = float(min(1.0, np.sqrt(np.mean(np.square(frame))) * 3.0)) if len(frame) else 0.0
        await hub.broadcast({"type": "speak", "level": lvl, "active": True})
        await asyncio.sleep(0.1)
    await hub.broadcast({"type": "speak", "level": 0.0, "active": False})
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_voice.py -q`
Expected: 2 passed.

- [ ] **Step 5: Speak completed replies**

In `brain.ask`, accumulate deltas into a `reply` string; on the `done` broadcast, `asyncio.create_task(voice.speak(hub, reply))` (import `voice` at top).

- [ ] **Step 6: Frontend already reacts**

`hud.js` maps `speak` → `state.speak`; `core.js renderCore(speakLevel)` already swells/brightens the sphere. Confirm no change needed.

- [ ] **Step 7: Manual verify (requires key in `.env`)**

Mackenzie sets `ELEVENLABS_API_KEY` + `VOICE_ID` in `.env`. Ask Jarvis something → hear the reply, watch the sphere swell in time with the voice. Without a key: chat still works, `status voice offline` logged, sphere stays idle.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: elevenlabs voice out with sphere amplitude reactivity"
```

---

## Phase 6 — Vault panel + Obsidian graph

### Task 9: Obsidian client → vault status + graph data

**Files:**
- Create: `jarvis/services/vault.py`
- Modify: `jarvis/app.py`, `static/js/graph.js`, `static/js/hud.js`
- Test: `tests/test_vault.py`

- [ ] **Step 1: Write the failing test (build graph from note link data)**

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_vault.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `jarvis/services/vault.py`**

```python
import asyncio
import re
import requests
from jarvis import config

WIKILINK = re.compile(r"\[\[([^\]|#]+)")

def _base():
    return f"http://127.0.0.1:{config.OBSIDIAN_PORT}"

def _headers():
    return {"Authorization": f"Bearer {config.OBSIDIAN_API_KEY}"}

def build_graph(files, links) -> dict:
    def group(path): return path.split("/")[0] if "/" in path else "root"
    nodes = [{"id": f, "label": f.rsplit("/", 1)[-1].replace(".md", ""), "group": group(f)} for f in files]
    edges = []
    idx = {f.rsplit("/", 1)[-1].replace(".md", ""): f for f in files}
    for src, targets in links.items():
        for t in targets:
            key = t.rsplit("/", 1)[-1].replace(".md", "")
            dst = idx.get(key, t if t in files else None)
            if dst:
                edges.append({"s": src, "t": dst})
    return {"type": "graph", "nodes": nodes, "links": edges}

def _list_files():
    r = requests.get(f"{_base()}/vault/", headers=_headers(), timeout=5)
    r.raise_for_status()
    out, stack = [], list(r.json().get("files", []))
    # Local REST API returns a flat listing per dir; walk recursively
    return _walk("", timeout=5)

def _walk(path, timeout):
    r = requests.get(f"{_base()}/vault/{path}", headers=_headers(), timeout=timeout)
    r.raise_for_status()
    files = []
    for entry in r.json().get("files", []):
        full = f"{path}{entry}"
        if entry.endswith("/"):
            files += _walk(full, timeout)
        elif entry.endswith(".md"):
            files.append(full)
    return files

def _read_links(path):
    r = requests.get(f"{_base()}/vault/{path}", headers={**_headers(), "Accept": "text/markdown"}, timeout=5)
    r.raise_for_status()
    return WIKILINK.findall(r.text)

async def run(hub):
    if not config.OBSIDIAN_API_KEY:
        await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": "no OBSIDIAN_API_KEY"})
        return
    while True:
        try:
            files = await asyncio.to_thread(_list_files)
            links = {}
            for f in files:
                links[f] = await asyncio.to_thread(_read_links, f)
            await hub.broadcast(build_graph(files, links))
            await hub.broadcast({"type": "vault", "projects": ["Jarvis"], "threads": 3, "lastNote": files[-1] if files else "-"})
        except Exception as e:
            await hub.broadcast({"type": "status", "service": "vault", "state": "offline", "detail": str(e)})
        await asyncio.sleep(60)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_vault.py -q`
Expected: 1 passed.

- [ ] **Step 5: Start vault service + render real graph**

`app.py` startup: `asyncio.create_task(vault.run(hub))`.
`graph.js`: replace the mock node generator with a simple force layout over the received `{nodes,links}` — initialize node positions randomly, each frame apply (a) repulsion between nodes, (b) spring attraction along links, (c) centering; draw links as faint lilac lines and nodes as pastel glowing dots colored by `group`. Use the message from `state.graph`; keep the mock generator only as the pre-data fallback.

- [ ] **Step 6: Manual verify (Obsidian running with Local REST API)**

Set `OBSIDIAN_API_KEY` in `.env`. Run HUD, click GRAPH → your real notes appear as nodes, wikilinks as edges, drifting in the pastel force layout.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: obsidian vault status + real graph tab"
```

---

## Phase 7 — Google Calendar → Today

### Task 10: Calendar OAuth + today's events

**Files:**
- Create: `jarvis/services/calendar.py`
- Modify: `jarvis/app.py`, `static/js/hud.js`
- Create: `scripts/gcal_auth.py` (one-time consent helper)
- Test: `tests/test_calendar.py`

- [ ] **Step 1: Write the failing test (format events for the Today panel)**

```python
from jarvis.services.calendar import format_events

def test_format_events_sorts_and_labels():
    raw = [
        {"start": {"dateTime": "2026-08-06T14:00:00-04:00"}, "summary": "Interview"},
        {"start": {"dateTime": "2026-08-06T09:00:00-04:00"}, "summary": "Stand-up"},
    ]
    out = format_events(raw)
    assert out == {"type": "calendar", "events": [
        {"time": "9:00 AM", "title": "Stand-up"},
        {"time": "2:00 PM", "title": "Interview"},
    ]}
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_calendar.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `jarvis/services/calendar.py`**

```python
import asyncio
import datetime as dt
from jarvis import config

def _fmt_time(iso: str) -> str:
    t = dt.datetime.fromisoformat(iso)
    h = t.hour % 12 or 12
    ap = "AM" if t.hour < 12 else "PM"
    return f"{h}:{t.minute:02d} {ap}"

def format_events(raw) -> dict:
    items = []
    for e in raw:
        start = e.get("start", {}).get("dateTime")
        if not start:
            continue
        items.append((start, {"time": _fmt_time(start), "title": e.get("summary", "(no title)")}))
    items.sort(key=lambda x: x[0])
    return {"type": "calendar", "events": [i[1] for i in items]}

def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file("token.json",
        ["https://www.googleapis.com/auth/calendar.readonly"])
    return build("calendar", "v3", credentials=creds)

def _today_events():
    svc = _service()
    now = dt.datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    res = svc.events().list(calendarId=config.GOOGLE_CALENDAR_ID,
        timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime").execute()
    return res.get("items", [])

async def run(hub):
    import os
    if not os.path.exists("token.json"):
        await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": "not authorized"})
        return
    while True:
        try:
            raw = await asyncio.to_thread(_today_events)
            await hub.broadcast(format_events(raw))
        except Exception as e:
            await hub.broadcast({"type": "status", "service": "calendar", "state": "offline", "detail": str(e)})
        await asyncio.sleep(300)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_calendar.py -q`
Expected: 1 passed.

- [ ] **Step 5: Write `scripts/gcal_auth.py` (Mackenzie runs once)**

```python
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)
open("token.json", "w").write(creds.to_json())
print("Saved token.json")
```

Mackenzie: create a Google Cloud project, enable Calendar API, download OAuth `credentials.json` into the repo, then `.venv/Scripts/python scripts/gcal_auth.py` and click through consent.

- [ ] **Step 6: Start calendar service + render Today**

`app.py` startup: `asyncio.create_task(calendar.run(hub))`.
`hud.js` `applyCalendar(m)`: rebuild the Today `<ul>` from `m.events`, cycling the pastel dot colors.

- [ ] **Step 7: Manual verify**

After auth, the Today panel shows real events in 12-hour format. Without `token.json`: panel shows "offline", HUD unaffected.

- [ ] **Step 8: Commit + tag v0.1**

```bash
git add -A && git commit -m "feat: google calendar today panel"
git tag v0.1
```

---

## Self-Review

**Spec coverage:** pastel/pixel aesthetic (Task 3) · dark core panel + particle sphere (Task 3) · sphere reacts to TTS (Task 8) · pink mic waveform reacts to mic (Task 7) · open-mic + mute (Task 7) · 12-hour clock (Task 3) · CORE/GRAPH tabs (Task 3) · graph rebuilt from real vault via Obsidian (Task 9) · vitals (Task 5) · chat via Claude Code CLI (Task 6) · voice via ElevenLabs, keys in `.env` (Task 8) · calendar via Google OAuth (Task 10) · graceful degradation via `status` messages (Tasks 7–10) · separate repo (Task 0). All spec sections map to a task.

**Placeholder scan:** no TBD/TODO steps; every code step contains real code. The only user-side manual steps are the ElevenLabs key, Obsidian API key, and Google OAuth consent — all explicitly Mackenzie's actions per the spec.

**Type consistency:** message `type` strings are consistent across backend broadcasters and the `hud.js` dispatch (`vitals`/`chat`/`mic`/`speak`/`vault`/`graph`/`calendar`/`status`). `ears.set_muted`/`is_muted`, `voice.available`/`speak`, `vault.build_graph`, `calendar.format_events` are each defined once and called with matching signatures.

## Notes / risks carried from the spec
- Claude Code CLI `stream-json` event shape may differ slightly by version; `parse_stream_line` ignores unrecognized lines, so a shape change degrades to "no deltas" rather than a crash — verify against the installed CLI in Task 6 Step 7 and adjust the parser if needed.
- Obsidian Local REST API must be installed/enabled in the vault (community plugin) for Task 9; if absent, the vault service just reports offline.
