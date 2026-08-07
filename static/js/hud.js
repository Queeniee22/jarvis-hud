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
    else if (m.type === "graph") state.graph = m;
    else if (m.type === "calendar") applyCalendar(m);
    else if (m.type === "heard") applyHeard(m);
    else if (m.type === "status") applyStatus(m);
  };
  function send(obj){ if (ws.readyState===1) ws.send(JSON.stringify(obj)); }

  const muteBtn = document.getElementById('muteBtn');
  function updateMuteBtn(){
    if (!muteBtn) return;
    muteBtn.textContent = state.mic.muted ? 'MUTED' : 'MUTE';
    muteBtn.classList.toggle('active', !!state.mic.muted);
  }
  if (muteBtn) {
    muteBtn.addEventListener('click', () => {
      send({type:'mute', value: !state.mic.muted});
    });
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
    const projects = Array.isArray(m.projects) ? m.projects.join(', ') : (m.projects || '');
    const threads = (typeof m.threads === 'number') ? m.threads : (m.threads || 0);
    const lastNote = m.lastNote || '—';
    const items = [
      `Projects: ${projects || '—'}`,
      `Open threads: ${threads}`,
      `Last note: ${lastNote}`
    ];
    list.innerHTML = items.map((text, i) =>
      `<li><span class="dot ${dotClasses[i % dotClasses.length]}"></span>${text}</li>`
    ).join('');
  }
  function applyCalendar(m){ /* Phase 7 */ }
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

  function applyStatus(m){ console.warn("service", m.service, m.state, m.detail||""); }

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

  window.initCore();
  window.initGraph();
  window.initWave();
  frame();
})();
