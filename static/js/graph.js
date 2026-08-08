/* ---------- obsidian graph (mock fallback + real force-directed render) ---------- */
(function(){
  let gc, gx, GW, GH;
  const gcolors=['247,183,206','201,182,228','184,230,196','247,229,160'];

  // stable positions/velocities for real graph nodes, keyed by node id.
  // Kept module-internal -- hud.js and app code only ever get node ids/
  // labels back through the click callback, never the layout itself.
  const posMap = new Map();
  let groupColorMap = new Map();
  let groupIdx = 0;
  let spinAngle = 0;
  // Why there is no graph, when we know. A spinner says "any moment now";
  // if the vault is down that is a lie, and the tab spins until a refresh.
  let notice = null;

  // Nodes from the most recent renderGraph call, for hit-testing on
  // mousemove/click -- those are separate DOM event handlers, not part of
  // the render loop, so they need their own copy of "what's on screen now".
  let lastNodes = [];
  let hoveredId = null;
  // The node whose note is currently open beside the graph (set by hud.js),
  // so its label stays visible even after the mouse moves away.
  let openNodeId = null;
  let clickHandler = null;

  const HIT_RADIUS = 14; // canvas px, per the click-target spec

  function initGraph(){
    gc = document.getElementById('graph');
    gx = gc.getContext('2d');
    GW = gc.width; GH = gc.height;

    gc.addEventListener('mousemove', (e) => {
      const hit = nodeAt(e.clientX, e.clientY);
      hoveredId = hit ? hit.id : null;
      gc.style.cursor = hit ? 'pointer' : 'default';
    });
    gc.addEventListener('mouseleave', () => {
      hoveredId = null;
      gc.style.cursor = 'default';
    });
    gc.addEventListener('click', (e) => {
      const hit = nodeAt(e.clientX, e.clientY);
      if (hit && clickHandler) clickHandler(hit.id, hit.label);
    });
  }

  /* Convert a click/move in page space to canvas-buffer space and find the
     nearest node within HIT_RADIUS. The canvas has a fixed internal pixel
     size (gc.width/gc.height) but is scaled down by CSS max-width/max-height
     -- e.getBoundingClientRect() gives the on-screen box, so the ratio of
     buffer size to that box is the scale factor back to canvas space. */
  function nodeAt(clientX, clientY){
    if (!gc) return null;
    const r = gc.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    const x = (clientX - r.left) * (gc.width / r.width);
    const y = (clientY - r.top) * (gc.height / r.height);
    let best = null, bestDist = HIT_RADIUS;
    for (const n of lastNodes) {
      const p = posMap.get(n.id);
      if (!p) continue;
      const dx = p.x - x, dy = p.y - y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= bestDist) { bestDist = dist; best = n; }
    }
    return best;
  }

  function setGraphNodeClick(fn){ clickHandler = fn; }
  function setGraphOpenNode(id){ openNodeId = id || null; }

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

  function drawNodeLabel(nodes, id, color){
    const p = posMap.get(id);
    const n = nodes.find(n => n.id === id);
    if (!p || !n) return;
    gx.font = '10px "Pixelify Sans", sans-serif';
    gx.textAlign = 'center';
    gx.fillStyle = color;
    gx.fillText(n.label, p.x, p.y - 12);
  }

  function renderGraph(data){
    gx.clearRect(0,0,GW,GH);

    if(data && data.nodes && data.links){
      const nodes = data.nodes, links = data.links;
      lastNodes = nodes; // for nodeAt() hit-testing outside the render loop
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
        // Hovered/open nodes draw bigger and brighter -- the only signal
        // (besides the cursor) that a node is a clickable target at all.
        const emphasized = n.id === hoveredId || n.id === openNodeId;
        const radius = emphasized ? 6 : 3;
        gx.beginPath();gx.fillStyle='rgba('+c+',0.95)';
        gx.shadowColor='rgba('+c+',0.9)';gx.shadowBlur = emphasized ? 14 : 8;
        gx.arc(p.x,p.y,radius,0,7);gx.fill();
      }
      gx.shadowBlur=0;

      // Labels drawn last, above every node/link, so hovered and
      // currently-open notes are legible regardless of what's underneath.
      if (openNodeId && openNodeId !== hoveredId) drawNodeLabel(nodes, openNodeId, 'rgba(184,230,196,0.95)');
      if (hoveredId) drawNodeLabel(nodes, hoveredId, 'rgba(247,183,206,0.95)');
      return;
    }

    /* fallback: say why if we know, otherwise we are genuinely still loading */
    if (notice) renderNotice(notice);
    else renderSpinner();
  }

  window.initGraph = initGraph;
  window.renderGraph = renderGraph;
  window.setGraphNotice = setGraphNotice;
  window.setGraphNodeClick = setGraphNodeClick;
  window.setGraphOpenNode = setGraphOpenNode;
})();
