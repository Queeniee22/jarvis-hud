/* ---------- hud shell: clock, tabs, single render loop ---------- */
(function(){
  /* central state + websocket client */
  const state = { speak:0, mic:{level:0,muted:false}, graph:null, vitals:null };
  let speakFromServer = false;
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === "vitals") applyVitals(m);
    else if (m.type === "mic") {
      state.mic = m;
      window.setMic(m.level, m.muted || m.gated);
      updateMuteBtn();
      const mic = document.querySelector(".mic");
      if (mic) mic.classList.toggle("gated", !!m.gated && !m.muted);
    }
    else if (m.type === "speak") { speakFromServer = true; state.speak = m.active ? m.level : 0; }
    else if (m.type === "chat") applyChat(m);
    else if (m.type === "vault") applyVault(m);
    else if (m.type === "graph") {
      state.graph = m;
      // Make the nodes searchable immediately, without waiting for the
      // GRAPH tab to be opened and drawn at least once.
      if (window.setGraphNodes) window.setGraphNodes(m.nodes);
      // A search typed before the data landed should now find its matches.
      runGraphSearch();
      // Real data arrived: the vault recovered, so drop any offline notice.
      if (window.setGraphNotice) window.setGraphNotice(null);
    }
    else if (m.type === "calendar") applyCalendar(m);
    else if (m.type === "thinking") applyThinking(m);
    else if (m.type === "ask") applyAsk(m);
    else if (m.type === "heard") applyHeard(m);
    else if (m.type === "status") applyStatus(m);
    else if (m.type === "note") applyNote(m);
    else if (m.type === "note_saved") applyNoteSaved(m);
    else if (m.type === "note_error") applyNoteError(m);
  };
  function send(obj){ if (ws.readyState===1) ws.send(JSON.stringify(obj)); }

  /* push-to-talk: hold SPACE (or hold the button) to talk, release to send.
     Releasing is the end of the turn, so nothing has to guess whether you
     have finished a sentence. */
  const talkBtn = document.getElementById('muteBtn');
  let pttDown = false;
  function setPtt(on){
    if (on === pttDown) return;          // ignore key auto-repeat
    pttDown = on;
    send({type:'ptt', value:on});
    document.body.classList.toggle('talking', on);
    if (talkBtn) {
      talkBtn.textContent = on ? 'LISTENING' : 'HOLD SPACE';
      talkBtn.classList.toggle('active', on);
    }
  }
  function updateMuteBtn(){
    if (!talkBtn || pttDown) return;
    talkBtn.textContent = 'HOLD SPACE';
  }
  const typing = (e) => {
    const el = e.target;
    return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
  };
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && !typing(e)) { e.preventDefault(); setPtt(true); }
  });
  window.addEventListener('keyup', (e) => {
    if (e.code === 'Space' && !typing(e)) { e.preventDefault(); setPtt(false); }
  });
  // Releasing outside the window must not leave the mic stuck open.
  window.addEventListener('blur', () => setPtt(false));
  if (talkBtn) {
    talkBtn.addEventListener('mousedown', (e) => { e.preventDefault(); setPtt(true); });
    window.addEventListener('mouseup', () => setPtt(false));
    talkBtn.addEventListener('touchstart', (e) => { e.preventDefault(); setPtt(true); }, {passive:false});
    window.addEventListener('touchend', () => setPtt(false));
  }

  function applyVitals(m){
    document.querySelector(".f1").style.width = m.cpu + "%";
    document.querySelector(".f2").style.width = m.ram + "%";
    document.querySelector(".f3").style.width = m.disk + "%";
    const pcts = document.querySelectorAll(".pct");
    pcts[0].textContent = m.cpu + "%";
    pcts[1].textContent = m.ram + "%";
    pcts[2].textContent = m.disk + "%";
  }
  const chatLog = document.getElementById('chatLog');
  let currentJarvisLine = null;
  function scrollChatBottom(){ if (chatLog) chatLog.scrollTop = chatLog.scrollHeight; }
  function applyChat(m){
    if (!chatLog) return;
    if (m.role === 'you') {
      const line = document.createElement('div');
      line.className = 'msg';
      line.innerHTML = '<span class="who u">YOU</span>';
      line.appendChild(document.createTextNode(m.delta || ''));
      chatLog.appendChild(line);
      currentJarvisLine = null;
      scrollChatBottom();
    } else if (m.role === 'jarvis') {
      if (!currentJarvisLine) {
        currentJarvisLine = document.createElement('div');
        currentJarvisLine.className = 'msg';
        currentJarvisLine.innerHTML = '<span class="who j">JARVIS</span><span class="jtext"></span>';
        chatLog.appendChild(currentJarvisLine);
      }
      if (m.delta) {
        currentJarvisLine.querySelector('.jtext').textContent += m.delta;
      }
      scrollChatBottom();
      if (m.done) currentJarvisLine = null;
    }
  }
  const dotClasses = ['mint','','lil','butter'];
  function applyVault(m){
    const list = document.getElementById('vaultList');
    if (!list) return;
    const items = [];
    if (typeof m.notes === 'number') items.push(`Notes: ${m.notes}`);
    if (typeof m.links === 'number') items.push(`Links: ${m.links}`);
    if (m.lastNote) items.push(`Last edited: ${m.lastNote}${m.lastEditedMs ? ' · ' + ago(m.lastEditedMs) : ''}`);

    // The big readout under the sphere. It shipped as a hardcoded 135,000
    // from the mockup -- a number that described nothing.
    const big = document.getElementById('bigNum');
    if (big && typeof m.words === 'number') {
      big.innerHTML = m.words.toLocaleString() + '<small>WORDS INDEXED</small>';
    }
    if (!items.length) items.push('vault empty');
    list.innerHTML = items.map((text, i) =>
      `<li><span class="dot ${dotClasses[i % dotClasses.length]}"></span>${text}</li>`
    ).join('');
  }

  /* "3m ago" beats a raw timestamp for the one question the panel answers:
     is this vault stale, or did I just touch it? */
  function ago(ms){
    const secs = Math.max(0, Math.floor((Date.now() - ms) / 1000));
    if (secs < 60) return 'just now';
    const mins = Math.floor(secs / 60);
    if (mins < 60) return mins + 'm ago';
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + 'h ago';
    return Math.floor(hours / 24) + 'd ago';
  }

  /* Graph search. The box shipped as a plain <div> from the mockup -- it
     looked like a search field and could not be typed in. */
  const graphSearch = document.getElementById('graphSearch');
  const graphSearchCount = document.getElementById('graphSearchCount');
  function runGraphSearch(){
    if (!graphSearch || !window.setGraphFilter) return;
    const q = graphSearch.value;
    const n = window.setGraphFilter(q);
    if (!graphSearchCount) return;
    if (!q.trim()) {
      graphSearchCount.classList.add('hide');
    } else {
      graphSearchCount.classList.remove('hide');
      graphSearchCount.textContent = n === 0 ? 'no matches' : `${n} match${n === 1 ? '' : 'es'}`;
      graphSearchCount.classList.toggle('none', n === 0);
    }
  }
  if (graphSearch) {
    graphSearch.addEventListener('input', runGraphSearch);
    graphSearch.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        graphSearch.value = '';
        runGraphSearch();
        graphSearch.blur();
      } else if (e.key === 'Enter') {
        // One match is unambiguous, so open it rather than making him find
        // the highlighted dot and click it.
        const hits = window.graphMatches ? window.graphMatches() : [];
        if (hits.length) openNote(hits[0]);
      }
    });
  }

  /* Service health panel. Every service reports online/offline/error; a row
     that has never reported stays "—" rather than claiming to be fine. */
  const SERVICE_WHAT = {
    ears: 'Speech to text. Runs faster-whisper locally while you hold the talk key.',
    voice: 'Text to speech via ElevenLabs. Your replies are spoken with this.',
    brain: 'The Claude Code CLI, running inside your vault so it can read and write notes.',
    vault: 'Obsidian Local REST API — the vault panel, the graph, and note editing.',
    calendar: 'Google Calendar, read-only. Fills the TODAY panel.',
  };
  const serviceSeen = {};   // service -> when its state last changed

  function applyServiceStatus(m){
    const row = document.querySelector(`#serviceList li[data-service="${m.service}"]`);
    if (!row) return;
    const dot = row.querySelector('.dot');
    const label = row.querySelector('.svcstate');
    dot.classList.remove('online', 'offline', 'error');
    const state = m.state === 'ready' ? 'online' : m.state;
    if (state) dot.classList.add(state);
    if (label) label.textContent = state || '—';
    serviceSeen[m.service] = { state, detail: m.detail || '', at: Date.now() };
  }

  /* A custom tooltip rather than title=. The native one waited a second,
     drew in OS chrome, and only ever repeated the state already on the row. */
  const svcTip = document.getElementById('svcTip');
  function showServiceTip(row){
    if (!svcTip) return;
    const name = row.dataset.service;
    const seen = serviceSeen[name];
    const parts = [`<span class="tipname">${name.toUpperCase()}</span>`];
    if (SERVICE_WHAT[name]) parts.push(`<span class="tipwhat">${SERVICE_WHAT[name]}</span>`);
    if (seen && seen.detail) parts.push(`<span class="tipdetail">${seen.detail}</span>`);
    parts.push(seen
      ? `<span class="tipwhen">${seen.state} · reported ${ago(seen.at)}</span>`
      : `<span class="tipwhen">has not reported yet</span>`);
    svcTip.innerHTML = parts.join('');
    svcTip.classList.remove('hide');

    // Anchor to the left of the row: the panel is on the right edge, so a
    // tooltip placed rightward would run off screen.
    const r = row.getBoundingClientRect();
    const t = svcTip.getBoundingClientRect();
    svcTip.style.left = Math.max(8, r.left - t.width - 10) + 'px';
    svcTip.style.top = Math.max(8, Math.min(window.innerHeight - t.height - 8, r.top - 4)) + 'px';
  }
  function hideServiceTip(){ if (svcTip) svcTip.classList.add('hide'); }

  document.querySelectorAll('#serviceList li').forEach(row => {
    row.addEventListener('mouseenter', () => showServiceTip(row));
    row.addEventListener('mouseleave', hideServiceTip);
  });

  function applyCalendar(m){
    const list = document.getElementById('todayList');
    if (!list) return;
    const events = Array.isArray(m.events) ? m.events : [];
    if (!events.length) {
      list.innerHTML = '<li><span class="dot"></span>nothing today</li>';
      return;
    }
    list.innerHTML = events.map((ev, i) =>
      `<li><span class="dot ${dotClasses[i % dotClasses.length]}"></span>${ev.time} &nbsp;${ev.title}</li>`
    ).join('');
  }
  /* "thinking" indicator. Counts elapsed seconds rather than sitting static,
     so a turn that is merely slow looks different from one that is wedged. */
  let thinkTimer = null;
  let thinkStart = 0;
  function applyThinking(m){
    const box = document.getElementById('thinking');
    const time = document.getElementById('thinkTime');
    if (!box) return;
    if (m.active) {
      thinkStart = Date.now();
      if (time) time.textContent = '0s';
      box.classList.remove('hide');
      clearInterval(thinkTimer);
      thinkTimer = setInterval(() => {
        if (time) time.textContent = Math.floor((Date.now() - thinkStart) / 1000) + 's';
      }, 500);
    } else {
      clearInterval(thinkTimer);
      thinkTimer = null;
      box.classList.add('hide');
    }
  }

  /* clickable option cards -- answering by click instead of speaking */
  function clearAsk(){
    const box = document.getElementById('askBox');
    if (box) { box.classList.add('hide'); box.innerHTML = ''; }
  }
  function applyAsk(m){
    const box = document.getElementById('askBox');
    if (!box || !m.question || !Array.isArray(m.options) || !m.options.length) return;
    box.innerHTML = '';
    const q = document.createElement('div');
    q.className = 'askq';
    q.textContent = m.question;
    box.appendChild(q);
    const row = document.createElement('div');
    row.className = 'askrow';
    m.options.forEach((opt, i) => {
      const b = document.createElement('button');
      b.className = 'askopt';
      b.innerHTML = '<span class="asknum">' + (i + 1) + '</span>';
      b.appendChild(document.createTextNode(opt));
      b.addEventListener('click', () => { send({type:'choice', text: opt}); clearAsk(); });
      row.appendChild(b);
    });
    box.appendChild(row);
    box.classList.remove('hide');
  }
  // number keys pick an option without reaching for the mouse
  window.addEventListener('keydown', (e) => {
    const box = document.getElementById('askBox');
    if (!box || box.classList.contains('hide')) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= 9) {
      const btn = box.querySelectorAll('.askopt')[n - 1];
      if (btn) { e.preventDefault(); btn.click(); }
    }
  });

  let heardTimer = null;
  function applyHeard(m){
    const el = document.getElementById("heard");
    if (!el || !m.text) return;
    el.textContent = m.text;
    el.classList.add("show");
    clearTimeout(heardTimer);
    // Long enough to read, short enough that it doesn't linger as clutter.
    heardTimer = setTimeout(() => el.classList.remove("show"), 6000);
  }

  function offlineList(id, text){
    const list = document.getElementById(id);
    if (list) list.innerHTML = '<li><span class="dot"></span>' + text + '</li>';
  }
  function applyStatus(m){
    console.warn("service", m.service, m.state, m.detail||"");
    applyServiceStatus(m);
    if (m.state !== "offline") return;
    if (m.service === "calendar") {
      offlineList('todayList', 'calendar offline');
    } else if (m.service === "vault") {
      // The panel ships with placeholder rows; leaving them up during an
      // outage shows stale numbers as though they were live.
      offlineList('vaultList', 'vault offline');
      // The graph is vault data too -- say why instead of spinning forever.
      if (window.setGraphNotice) window.setGraphNotice(m.detail || '');
    }
  }

  /* Note panel: click a graph node to read that note beside the graph, edit
     it, and save back to the vault. graph.js only ever hands us an id/label
     through the click callback -- it never touches the DOM here. */
  const notePanel = document.getElementById('notePanel');
  const noteTitleEl = document.getElementById('noteTitle');
  const notePathEl = document.getElementById('notePath');
  const noteBodyEl = document.getElementById('noteBody');
  const noteSaveBtn = document.getElementById('noteSave');
  const noteSavedEl = document.getElementById('noteSaved');
  const noteErrorEl = document.getElementById('noteError');
  const noteCloseBtn = document.getElementById('noteClose');
  let noteState = { path: null, original: '' };
  let noteSavedTimer = null;

  function noteBasename(path){
    const name = path.split('/').pop();
    return name.endsWith('.md') ? name.slice(0, -3) : name;
  }
  function noteDirty(){
    return noteState.path !== null && noteBodyEl && noteBodyEl.value !== noteState.original;
  }
  // A plain confirm() is enough here -- this is a local single-user HUD,
  // not a page that needs a styled modal for one rare "are you sure".
  function noteConfirmDiscard(){
    return !noteDirty() || confirm('Discard unsaved changes to this note?');
  }
  function openNote(path){
    if (noteState.path === path && notePanel && !notePanel.classList.contains('hide')) return;
    if (!noteConfirmDiscard()) return;
    send({type:'note_open', path});
  }
  function applyNote(m){
    if (!notePanel || !m.path) return;
    noteState = { path: m.path, original: m.content || '' };
    noteTitleEl.textContent = noteBasename(m.path);
    notePathEl.textContent = m.path;
    noteBodyEl.value = m.content || '';
    noteErrorEl.textContent = '';
    notePanel.classList.remove('hide');
    if (window.setGraphOpenNode) window.setGraphOpenNode(m.path);
  }
  function applyNoteSaved(m){
    if (!noteState.path || noteState.path !== m.path) return;
    noteState.original = noteBodyEl.value; // this exact text is now on disk
    noteErrorEl.textContent = '';
    noteSavedEl.classList.add('show');
    clearTimeout(noteSavedTimer);
    noteSavedTimer = setTimeout(() => noteSavedEl.classList.remove('show'), 2000);
  }
  function applyNoteError(m){
    if (noteErrorEl) noteErrorEl.textContent = m.detail || 'save failed';
  }
  function closeNote(){
    if (!noteConfirmDiscard()) return;
    noteState = { path: null, original: '' };
    if (notePanel) notePanel.classList.add('hide');
    if (window.setGraphOpenNode) window.setGraphOpenNode(null);
  }
  function saveNote(){
    if (!noteState.path) return;
    send({type:'note_save', path: noteState.path, content: noteBodyEl.value});
  }
  if (window.setGraphNodeClick) window.setGraphNodeClick((id) => openNote(id));
  if (noteSaveBtn) noteSaveBtn.addEventListener('click', saveNote);
  if (noteCloseBtn) noteCloseBtn.addEventListener('click', closeNote);
  if (noteBodyEl) {
    noteBodyEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault(); // otherwise the browser's own Save dialog pops up
        saveNote();
      }
    });
  }

  /* live clock, 12-hour am/pm */
  const clockEl=document.getElementById('clock');
  function tick(){
    const d=new Date();
    const y=d.getFullYear(),mo=String(d.getMonth()+1).padStart(2,'0'),da=String(d.getDate()).padStart(2,'0');
    let h=d.getHours();const ap=h<12?'AM':'PM';h=h%12;if(h===0)h=12;
    const mi=String(d.getMinutes()).padStart(2,'0');
    clockEl.textContent=`${y}-${mo}-${da} · ${h}:${mi} ${ap}`;
  }
  tick();setInterval(tick,1000);

  /* CORE/GRAPH tab switching */
  let mode='core';
  document.getElementById('tabCore').onclick=()=>setMode('core');
  document.getElementById('tabGraph').onclick=()=>setMode('graph');
  function setMode(m){
    mode=m;
    document.getElementById('tabCore').classList.toggle('on',m==='core');
    document.getElementById('tabGraph').classList.toggle('on',m==='graph');
    document.getElementById('viewCore').classList.toggle('hide',m!=='core');
    document.getElementById('viewGraph').classList.toggle('hide',m!=='graph');
  }

  /* speak amplitude simulation (mock, until Task 4 wires real data) */
  const speakBadge=document.getElementById('speakbadge');
  let currentSpeak=0;
  let currentGraphData=null; // fallback graph until real data is wired

  let f=0;
  function frame(){
    f++;
    const cycle=(f%520)/520;
    currentSpeak=cycle<0.45?(0.5+0.5*Math.sin(f*0.35))*(1-Math.abs(cycle-0.22)/0.22):0;
    currentSpeak=Math.max(0,currentSpeak);
    const activeSpeak = speakFromServer ? state.speak : currentSpeak;
    speakBadge.style.display=activeSpeak>0.05?'block':'none';

    if(mode==='core'){
      window.renderCore(activeSpeak);
    } else {
      window.renderGraph(state.graph!==null ? state.graph : currentGraphData);
    }
    requestAnimationFrame(frame);
  }

  const chatInput = document.getElementById('chatInput');
  if (chatInput) {
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const value = chatInput.value.trim();
        if (value) {
          send({type:'say', text:value});
          chatInput.value = '';
        }
      }
    });
  }

  // Debug handle: lets the UI be exercised without a live conversation.
  window.__hud = {
    applyAsk, clearAsk, applyHeard, applyThinking, applyVault, applyServiceStatus, showServiceTip, hideServiceTip, ago, send,
    applyNote, applyNoteSaved, applyNoteError, openNote, closeNote, saveNote,
    noteState: () => noteState,
  };

  window.initCore();
  window.initGraph();
  window.initWave();
  frame();
})();
