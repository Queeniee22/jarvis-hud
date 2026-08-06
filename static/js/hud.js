/* ---------- hud shell: clock, tabs, single render loop ---------- */
(function(){
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
    speakBadge.style.display=currentSpeak>0.05?'block':'none';

    if(mode==='core'){
      window.renderCore(currentSpeak);
    } else {
      window.renderGraph(currentGraphData);
    }
    requestAnimationFrame(frame);
  }

  window.initCore();
  window.initGraph();
  window.initWave();
  frame();
})();
