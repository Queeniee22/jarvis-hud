/* ---------- obsidian graph (mock fallback + real force-directed render) ---------- */
(function(){
  let gc, gx, GW, GH;
  const gcolors=['247,183,206','201,182,228','184,230,196','247,229,160'];

  // stable positions/velocities for real graph nodes, keyed by node id
  const posMap = new Map();
  let groupColorMap = new Map();
  let groupIdx = 0;
  let spinAngle = 0;
  // Why there is no graph, when we know. A spinner says "any moment now";
  // if the vault is down that is a lie, and the tab spins until a refresh.
  let notice = null;

  function initGraph(){
    gc = document.getElementById('graph');
    gx = gc.getContext('2d');
    GW = gc.width; GH = gc.height;
  }

  function setGraphNotice(text){ notice = text || null; }

  function renderNotice(text){
    const cx = GW/2, cy = GH/2;
    gx.fillStyle = 'rgba(201,182,228,0.85)';
    gx.font = '13px sans-serif';
    gx.textAlign = 'center';
    gx.fillText('vault offline', cx, cy);
    if (text) {
      gx.fillStyle = 'rgba(201,182,228,0.5)';
      gx.font = '11px sans-serif';
      const clipped = text.length > 64 ? text.slice(0, 63) + '…' : text;
      gx.fillText(clipped, cx, cy + 20);
    }
  }

  function renderSpinner(){
    const cx = GW/2, cy = GH/2, r = 24;
    spinAngle += 0.08;
    gx.lineWidth = 3;
    gx.strokeStyle = 'rgba(201,182,228,0.9)';
    gx.beginPath();
    gx.arc(cx, cy, r, spinAngle, spinAngle + Math.PI*1.2);
    gx.stroke();
    gx.fillStyle = 'rgba(201,182,228,0.6)';
    gx.font = '12px sans-serif';
    gx.textAlign = 'center';
    gx.fillText('loading graph…', cx, cy + r + 20);
  }

  function colorForGroup(group){
    if(!groupColorMap.has(group)){
      groupColorMap.set(group, gcolors[groupIdx % gcolors.length]);
      groupIdx++;
    }
    return groupColorMap.get(group);
  }

  function ensurePos(id){
    let p = posMap.get(id);
    if(!p){
      const ang=Math.random()*6.283, rad=40+Math.random()*230;
      p = {
        x: GW/2 + Math.cos(ang)*rad,
        y: GH/2 + Math.sin(ang)*rad,
        vx: 0, vy: 0
      };
      posMap.set(id, p);
    }
    return p;
  }

  function stepForceLayout(nodes, links){
    const REPULSION = 900;
    const SPRING = 0.01;
    const SPRING_LEN = 70;
    const CENTER_PULL = 0.002;
    const DAMPING = 0.85;
    const cx = GW/2, cy = GH/2;

    // repulsion between all pairs
    for(let i=0;i<nodes.length;i++){
      const a = ensurePos(nodes[i].id);
      for(let j=i+1;j<nodes.length;j++){
        const b = ensurePos(nodes[j].id);
        let dx = a.x - b.x, dy = a.y - b.y;
        let distSq = dx*dx + dy*dy;
        if(distSq < 1) distSq = 1;
        const dist = Math.sqrt(distSq);
        const force = REPULSION / distSq;
        const fx = (dx/dist) * force, fy = (dy/dist) * force;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }

    // spring attraction along links
    for(const l of links){
      const a = ensurePos(l.s), b = ensurePos(l.t);
      let dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.sqrt(dx*dx+dy*dy) || 1;
      const force = (dist - SPRING_LEN) * SPRING;
      const fx = (dx/dist) * force, fy = (dy/dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    // centering + damping + integrate + clamp
    for(const n of nodes){
      const p = ensurePos(n.id);
      p.vx += (cx - p.x) * CENTER_PULL;
      p.vy += (cy - p.y) * CENTER_PULL;
      p.vx *= DAMPING; p.vy *= DAMPING;
      p.x += p.vx; p.y += p.vy;
      p.x = Math.max(20, Math.min(GW-20, p.x));
      p.y = Math.max(20, Math.min(GH-20, p.y));
    }
  }

  function renderGraph(data){
    gx.clearRect(0,0,GW,GH);

    if(data && data.nodes && data.links){
      const nodes = data.nodes, links = data.links;
      stepForceLayout(nodes, links);

      gx.lineWidth=1;
      for(const l of links){
        const A = posMap.get(l.s), B = posMap.get(l.t);
        if(!A || !B) continue;
        gx.strokeStyle='rgba(201,182,228,0.18)';
        gx.beginPath();gx.moveTo(A.x,A.y);gx.lineTo(B.x,B.y);gx.stroke();
      }
      for(const n of nodes){
        const p = posMap.get(n.id);
        if(!p) continue;
        const c = colorForGroup(n.group);
        gx.beginPath();gx.fillStyle='rgba('+c+',0.95)';
        gx.shadowColor='rgba('+c+',0.9)';gx.shadowBlur=8;
        gx.arc(p.x,p.y,3,0,7);gx.fill();
      }
      gx.shadowBlur=0;
      return;
    }

    /* fallback: say why if we know, otherwise we are genuinely still loading */
    if (notice) renderNotice(notice);
    else renderSpinner();
  }

  window.initGraph = initGraph;
  window.renderGraph = renderGraph;
  window.setGraphNotice = setGraphNotice;
})();
