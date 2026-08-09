/* Load a HUD frontend module into a throwaway DOM.
 *
 * The frontend files are IIFEs that read the DOM at load time and hang their
 * API on `window`, so a test needs a document in place *before* the file is
 * evaluated. jsdom has no canvas implementation, so the 2D context is a fake
 * that records the calls made to it -- which is more useful than a real one
 * anyway: assertions can look at what was drawn instead of at pixels.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.join(HERE, '..', '..', 'static');

/** A 2D context that records every call, so tests can assert on drawing. */
export function fakeContext() {
  const calls = [];
  const record = (name) => (...args) => { calls.push({ name, args }); };
  return {
    calls,
    // state the code assigns to
    lineWidth: 1, strokeStyle: '', fillStyle: '', shadowColor: '',
    shadowBlur: 0, font: '', textAlign: '',
    beginPath: record('beginPath'), moveTo: record('moveTo'),
    lineTo: record('lineTo'), stroke: record('stroke'),
    arc: record('arc'), fill: record('fill'),
    fillText: record('fillText'), clearRect: record('clearRect'),
    fillRect: record('fillRect'),
    createRadialGradient: () => ({ addColorStop() {} }),
  };
}

/**
 * @param {string} file  filename under static/js, e.g. 'graph.js'
 * @param {string} html  body markup the module expects to find
 * @param {object} opts  { canvasRect } to control getBoundingClientRect
 */
export function loadModule(file, html, opts = {}) {
  const dom = new JSDOM(`<!doctype html><body>${html}</body>`, {
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const { window } = dom;

  const ctx = fakeContext();
  window.HTMLCanvasElement.prototype.getContext = () => ctx;

  // The canvas is scaled by CSS, so its on-screen box differs from its pixel
  // buffer. Tests control that box explicitly -- it is the whole point of the
  // coordinate-conversion tests.
  if (opts.canvasRect) {
    window.HTMLCanvasElement.prototype.getBoundingClientRect = function () {
      return opts.canvasRect;
    };
  }

  // hud.js opens a websocket at load time; jsdom has none, so give it an
  // inert stub that records what the page tried to send.
  const sent = [];
  window.WebSocket = class {
    constructor() { this.readyState = 1; setTimeout(() => this.onopen && this.onopen(), 0); }
    send(data) { sent.push(data); }
    close() {}
  };
  window.__sent = sent;

  // index.html loads core/graph/wave before hud.js, and hud.js calls into
  // them at startup -- so a test that loads hud.js alone would fail on
  // window.initCore. Accepts one filename or an ordered list.
  for (const name of [].concat(file)) {
    window.eval(fs.readFileSync(path.join(STATIC, 'js', name), 'utf8'));
  }
  return { window, document: window.document, ctx, dom };
}

/** The real page body, so tests exercise the markup that actually ships.
 *  Hand-maintained fixtures drift; this cannot. */
export function realHudMarkup() {
  const html = fs.readFileSync(path.join(STATIC, 'index.html'), 'utf8');
  const body = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  const inner = body ? body[1] : html;
  // Drop the <script> tags: the loader evaluates those files itself, in
  // order, and jsdom must not try to fetch them over HTTP.
  return inner.replace(/<script[\s\S]*?<\/script>/gi, '');
}

/** The markup graph.js expects: a stats readout and a sized canvas. */
export function graphMarkup({ width = 640, height = 640 } = {}) {
  return `
    <div class="gstats" id="gstats">NODES: --<br>LINKS: --<br>FPS: --</div>
    <canvas id="graph" width="${width}" height="${height}"></canvas>
  `;
}

/** Nodes/links shaped like a real vault payload. */
export function graphData(nodeCount, linkCount) {
  const nodes = [];
  const links = [];
  for (let i = 0; i < nodeCount; i++) {
    nodes.push({ id: `n${i}`, label: `note ${i}`, group: `g${i % 4}` });
  }
  for (let i = 0; i < linkCount; i++) {
    links.push({ s: `n${i % nodeCount}`, t: `n${(i * 7 + 3) % nodeCount}` });
  }
  return { type: 'graph', nodes, links };
}
