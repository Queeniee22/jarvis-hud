/* Tests for the vault graph: the stats readout and click hit-testing.
 *
 * Both areas shipped a real bug that in-browser eyeballing nearly missed --
 * a settling threshold that could never be reached, and hit-testing that
 * ignored CSS scaling. These lock those in.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, graphMarkup, graphData } from './hud-dom.mjs';

function statsText(document) {
  return document.getElementById('gstats').textContent;
}

describe('graph stats readout', () => {
  test('reports the real node and link counts, not mockup numbers', () => {
    const { window, document } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    window.renderGraph(graphData(23, 71));

    const text = statsText(document);
    assert.match(text, /NODES: 23/);
    assert.match(text, /LINKS: 71/);
    // the hardcoded mockup values that used to sit here regardless of vault
    assert.doesNotMatch(text, /902|3611/);
  });

  test('a different vault reports different counts', () => {
    const { window, document } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    window.renderGraph(graphData(5, 4));
    assert.match(statsText(document), /NODES: 5/);
    assert.match(statsText(document), /LINKS: 4/);
  });

  test('shows zeros and NO DATA when there is no graph, not stale counts', () => {
    const { window, document } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    window.renderGraph(graphData(23, 71));
    assert.match(statsText(document), /NODES: 23/);

    // vault goes away -- leaving 23 on screen would misdescribe an empty view
    window.renderGraph(null);
    const s = window.__graphStats();
    assert.equal(s.nodes, 0);
    assert.equal(s.links, 0);
    assert.equal(s.hasData, false);
  });

  test('reaches a settled state — the threshold must be attainable', () => {
    // Regression: the first version tested "per-node energy < 0.05", but this
    // layout asymptotes near 0.365 and never goes lower, so STABLE could
    // never appear on any vault. Settling is now relative, not absolute.
    // Asserted on the state rather than the text, because the DOM write is
    // throttled to 4x/sec and this loop runs far faster than that.
    const { window } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    const data = graphData(23, 71);

    let sawUnsettled = false;
    let sawSettled = false;
    for (let i = 0; i < 4000; i++) {
      window.renderGraph(data);
      const s = window.__graphStats();
      if (!s.settled) sawUnsettled = true;
      if (s.settled) { sawSettled = true; break; }
    }
    assert.ok(sawUnsettled, 'should be unsettled while the layout is still moving');
    assert.ok(sawSettled, 'should eventually settle — an unreachable threshold is a bug');
  });

  test('the energy it settles at is well above zero (why absolute thresholds fail)', () => {
    const { window } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    const data = graphData(23, 71);
    for (let i = 0; i < 3000; i++) window.renderGraph(data);
    const { perNode, settled } = window.__graphStats();
    assert.ok(settled, 'should have settled by now');
    assert.ok(perNode > 0.1,
      `settled energy is ${perNode.toFixed(3)}, not ~0 — any absolute "< small number" test is unreachable`);
  });

  test('reports a frame rate once it has frames to measure', () => {
    const { window, document } = loadModule('graph.js', graphMarkup());
    window.initGraph();
    const data = graphData(10, 12);
    for (let i = 0; i < 200; i++) window.renderGraph(data);
    assert.match(statsText(document), /FPS: \d+/);
    assert.equal(typeof window.__graphStats().fps, 'number');
  });
});

describe('node hit-testing', () => {
  // The canvas buffer is 640x640 but CSS displays it at 320x320 (scale 2).
  // Using clientX/offsetX directly would be wrong by that factor -- worse the
  // further from the origin -- which is exactly the bug this guards.
  const HALF_SCALE = { left: 0, top: 0, width: 320, height: 320, right: 320, bottom: 320 };

  function loadScaled() {
    const mod = loadModule('graph.js', graphMarkup(), { canvasRect: HALF_SCALE });
    mod.window.initGraph();
    return mod;
  }

  test('a click maps through CSS scaling to the right node', () => {
    const { window, document } = loadScaled();
    const data = graphData(12, 10);
    for (let i = 0; i < 300; i++) window.renderGraph(data);

    let clicked = null;
    window.setGraphNodeClick((id) => { clicked = id; });

    // Find where a node actually sits, in canvas-buffer space, by probing the
    // hover handler across the *displayed* box.
    const canvas = document.getElementById('graph');
    let hit = null;
    for (let x = 0; x < 320 && !hit; x += 2) {
      for (let y = 0; y < 320; y += 2) {
        canvas.dispatchEvent(new window.MouseEvent('mousemove', { clientX: x, clientY: y }));
        if (canvas.style.cursor === 'pointer') { hit = { x, y }; break; }
      }
    }
    assert.ok(hit, 'some node should be hoverable within the displayed box');

    canvas.dispatchEvent(new window.MouseEvent('click', { clientX: hit.x, clientY: hit.y }));
    assert.ok(clicked, 'clicking a hovered node should fire the click handler');
    assert.match(clicked, /^n\d+$/);
  });

  test('clicking empty space fires nothing', () => {
    const { window, document } = loadScaled();
    const data = graphData(3, 1);
    for (let i = 0; i < 200; i++) window.renderGraph(data);

    let clicked = null;
    window.setGraphNodeClick((id) => { clicked = id; });

    const canvas = document.getElementById('graph');
    // far corner: the layout centres nodes, so this is reliably empty
    canvas.dispatchEvent(new window.MouseEvent('mousemove', { clientX: 2, clientY: 2 }));
    canvas.dispatchEvent(new window.MouseEvent('click', { clientX: 2, clientY: 2 }));
    assert.equal(clicked, null);
    assert.notEqual(canvas.style.cursor, 'pointer');
  });

  test('a zero-sized canvas cannot divide by zero', () => {
    // The graph tab is display:none until selected, so getBoundingClientRect
    // legitimately returns 0x0 and the scale factor would be Infinity/NaN.
    const zero = { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 };
    const { window, document } = loadModule('graph.js', graphMarkup(), { canvasRect: zero });
    window.initGraph();
    window.renderGraph(graphData(5, 4));

    let clicked = null;
    window.setGraphNodeClick((id) => { clicked = id; });
    const canvas = document.getElementById('graph');
    assert.doesNotThrow(() => {
      canvas.dispatchEvent(new window.MouseEvent('click', { clientX: 10, clientY: 10 }));
    });
    assert.equal(clicked, null);
  });
});
