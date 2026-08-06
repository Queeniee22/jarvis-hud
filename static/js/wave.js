/* ---------- mic waveform ---------- */
(function(){
  let wave, bars = [];
  let f = 0;
  let realDataActive = false; // turned on once real mic data arrives via setMic

  function initWave(){
    wave = document.getElementById('wave');
    bars = [];
    for(let i=0;i<28;i++){
      const s=document.createElement('span');
      wave.appendChild(s);
      bars.push(s);
    }
  }

  function setMic(level, muted){
    realDataActive = true;
    const micdot = document.querySelector('.micdot');
    if(muted){
      for(const b of bars){
        b.style.height='20%';
        b.style.filter='grayscale(1)';
      }
      if(micdot) micdot.style.filter='grayscale(1)';
      return;
    }
    if(micdot) micdot.style.filter='';
    const lvl = Math.max(0, Math.min(1, level || 0));
    for(let i=0;i<bars.length;i++){
      const jitter = 0.6 + Math.random()*0.4;
      bars[i].style.filter='';
      bars[i].style.height=Math.min(100, Math.max(8, lvl*100*jitter)).toFixed(0)+'%';
    }
  }

  /* internal fallback animation, only runs until real data arrives */
  function fallbackTick(){
    if(!realDataActive && bars.length){
      f++;
      for(let i=0;i<bars.length;i++){
        const lvl=8+Math.abs(Math.sin(f*0.15+i*0.5))*Math.random()*90;
        bars[i].style.height=Math.min(100,lvl).toFixed(0)+'%';
      }
    }
    requestAnimationFrame(fallbackTick);
  }
  requestAnimationFrame(fallbackTick);

  window.initWave = initWave;
  window.setMic = setMic;
})();
