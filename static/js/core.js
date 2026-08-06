/* ---------- particle sphere ---------- */
(function(){
  let cv, ctx, W, H, cx, cy, baseR, pts, a;
  const N = 1400;

  function initCore(){
    cv = document.getElementById('orb');
    ctx = cv.getContext('2d');
    W = cv.width; H = cv.height; cx = W/2; cy = H/2; baseR = 210;
    pts = [];
    for(let i=0;i<N;i++){
      const y=1-(i/(N-1))*2, r=Math.sqrt(1-y*y), t=i*2.399963;
      const roll=Math.random();
      pts.push({x:Math.cos(t)*r,y:y,z:Math.sin(t)*r,
        c:roll<0.5?'247,183,206':(roll<0.8?'201,182,228':'184,230,196')});
    }
    a = 0;
  }

  function renderCore(speakLevel){
    const speak = speakLevel || 0;
    ctx.clearRect(0,0,W,H);
    a+=0.004;
    const R=baseR*(1+speak*0.18);
    const sa=Math.sin(a),ca=Math.cos(a);
    const glowA=0.18+speak*0.35;
    const g=ctx.createRadialGradient(cx,cy,0,cx,cy,R*1.3);
    g.addColorStop(0,'rgba(247,183,206,'+glowA.toFixed(2)+')');
    g.addColorStop(1,'rgba(247,183,206,0)');
    ctx.fillStyle=g;ctx.beginPath();ctx.arc(cx,cy,R*1.3,0,7);ctx.fill();
    const proj=pts.map(p=>{
      const x=p.x*ca-p.z*sa,z=p.x*sa+p.z*ca;
      const s=(z+1.6)/2.6;
      return {sx:cx+x*R,sy:cy+p.y*R,s,c:p.c,z};
    }).sort((m,n)=>m.z-n.z);
    for(const p of proj){
      const size=(1.3+p.s*2.6)*(1+speak*0.5);
      const alpha=Math.min(1,(0.3+p.s*0.75)+speak*0.2);
      ctx.beginPath();
      ctx.fillStyle='rgba('+p.c+','+alpha.toFixed(2)+')';
      ctx.shadowColor='rgba('+p.c+',0.95)';ctx.shadowBlur=(6+speak*8)*p.s;
      ctx.arc(p.sx,p.sy,size,0,7);ctx.fill();
    }
    ctx.shadowBlur=0;
  }

  window.initCore = initCore;
  window.renderCore = renderCore;
})();
