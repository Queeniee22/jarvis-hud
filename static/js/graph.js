/* ---------- obsidian graph (mock fallback + real force-directed render) ---------- */
(function(){
  let gc, gx, GW, GH;
  let mockNodes = [], mockLinks = [];
  const gcolors=['247,183,206','201,182,228','184,230,196','247,229,160'];

  // stable positions/velocities for real graph nodes, keyed by node id
  const posMap = new Map();
  let groupColorMap = new Map();
  let groupIdx = 0;

  function buildMock(){
    mockNodes = [];
    mockLinks = [];
    for(let i=0;i<70;i++){
      const ang=Math.random()*6.283,rad=40+Math.random()*230;
      mockNodes.push({x:GW/2+Math.cos(ang)*rad,y:GH/2+Math.sin(ang)*rad,
        vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,
        r:2+Math.random()*4,c:gcolors[i%4]});
    }
    for(let i=0;i<110;i++){
      const a=(Math.random()*70|0),b=(Math.random()*70|0);
      if(a!==b) mockLinks.push([a,b]);
    }
  }

  function initGraph(){
    gc = document.getElementById('graph');
    gx = gc.getContext('2d');
    GW = gc.width; GH = gc.height;
    buildMock();
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

    /* fallback: mock node/link simulation */
    for(const n of mockNodes){
      n.x+=n.vx;n.y+=n.vy;
      if(n.x<30||n.x>GW-30)n.vx*=-1; if(n.y<30||n.y>GH-30)n.vy*=-1;
    }
    gx.lineWidth=1;
    for(const [i,j] of mockLinks){
      const A=mockNodes[i],B=mockNodes[j];
      gx.strokeStyle='rgba(201,182,228,0.18)';
      gx.beginPath();gx.moveTo(A.x,A.y);gx.lineTo(B.x,B.y);gx.stroke();
    }
    for(const n of mockNodes){
      gx.beginPath();gx.fillStyle='rgba('+n.c+',0.95)';
      gx.shadowColor='rgba('+n.c+',0.9)';gx.shadowBlur=8;
      gx.arc(n.x,n.y,n.r,0,7);gx.fill();
    }
    gx.shadowBlur=0;
  }

  window.initGraph = initGraph;
  window.renderGraph = renderGraph;
})();
