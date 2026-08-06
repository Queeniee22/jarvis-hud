/* ---------- obsidian graph (mock fallback + real data render) ---------- */
(function(){
  let gc, gx, GW, GH;
  let mockNodes = [], mockLinks = [];
  const gcolors=['247,183,206','201,182,228','184,230,196','247,229,160'];

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

  function renderGraph(data){
    gx.clearRect(0,0,GW,GH);

    if(data && data.nodes && data.links){
      const nodes = data.nodes, links = data.links;
      gx.lineWidth=1;
      for(const l of links){
        const A = nodes[l[0]] !== undefined ? nodes[l[0]] : l.source;
        const B = nodes[l[1]] !== undefined ? nodes[l[1]] : l.target;
        if(!A || !B) continue;
        gx.strokeStyle='rgba(201,182,228,0.18)';
        gx.beginPath();gx.moveTo(A.x,A.y);gx.lineTo(B.x,B.y);gx.stroke();
      }
      for(const n of nodes){
        gx.beginPath();gx.fillStyle='rgba('+(n.c||gcolors[0])+',0.95)';
        gx.shadowColor='rgba('+(n.c||gcolors[0])+',0.9)';gx.shadowBlur=8;
        gx.arc(n.x,n.y,n.r||3,0,7);gx.fill();
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
