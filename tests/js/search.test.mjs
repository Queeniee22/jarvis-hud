/* Graph search. The box was a <div> from the mockup: it looked like a search
 * field and could not be typed in at all. */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, realHudMarkup, graphMarkup, graphData } from './hud-dom.mjs';

function withHud(fn) {
  const mod = loadModule(['core.js', 'graph.js', 'wave.js', 'hud.js'], realHudMarkup());
  try { fn(mod); } finally { mod.dom.window.close(); }
}

const VAULT = {
  type: 'graph',
  nodes: [
    { id: 'a.md', label: 'Debug Log', group: '02', tags: ['programming/debugging'] },
    { id: 'b.md', label: 'Working Style', group: '01', tags: ['preferences/style'] },
    { id: 'c.md', label: 'Jarvis HUD Design', group: '02', tags: ['programming/jarvis'] },
    { id: 'd.md', label: 'Goals', group: '04', tags: [] },
  ],
  links: [{ s: 'a.md', t: 'c.md' }],
};

describe('graph search', () => {
  test('the search box is a real input, not a div', () => withHud(({ document }) => {
    const box = document.getElementById('graphSearch');
    assert.ok(box, 'search box must exist');
    assert.equal(box.tagName, 'INPUT', 'a div cannot be typed into');
    assert.ok(box.placeholder.length > 0);
  }));

  test('matches note titles, case-insensitively', () => withHud(({ window }) => {
    window.renderGraph(VAULT);
    assert.equal(window.setGraphFilter('debug'), 1);
    assert.deepEqual(Array.from(window.graphMatches()), ['a.md']);
    assert.equal(window.setGraphFilter('DEBUG'), 1, 'search must not be case sensitive');
  }));

  test('a partial word matches several notes', () => withHud(({ window }) => {
    window.renderGraph(VAULT);
    assert.equal(window.setGraphFilter('g'), 4);   // Debug, Working, Design, Goals
  }));

  test('#tag searches tags, not titles', () => withHud(({ window }) => {
    window.renderGraph(VAULT);
    assert.equal(window.setGraphFilter('#programming'), 2);
    assert.deepEqual(Array.from(window.graphMatches()).sort(), ['a.md', 'c.md']);
    // 'programming' appears in no title, so this proves tags were consulted
    assert.equal(window.setGraphFilter('programming'), 0);
  }));

  test('an empty query clears the filter rather than matching nothing', () => withHud(({ window }) => {
    window.renderGraph(VAULT);
    window.setGraphFilter('debug');
    assert.equal(window.setGraphFilter(''), 0);
    assert.deepEqual(Array.from(window.graphMatches()), [], 'no filter means no highlight, not zero results');
  }));

  test('a bare # is not treated as a match-everything tag', () => withHud(({ window }) => {
    window.renderGraph(VAULT);
    assert.equal(window.setGraphFilter('#'), 0);
  }));

  test('typing updates the match count, and no match says so', () => withHud(({ window, document }) => {
    window.renderGraph(VAULT);
    const box = document.getElementById('graphSearch');
    const count = document.getElementById('graphSearchCount');

    box.value = 'debug';
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.match(count.textContent, /1 match$/);

    box.value = 'zzzz';
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.match(count.textContent, /no matches/);

    box.value = '';
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.ok(count.classList.contains('hide'), 'count hides when the box is empty');
  }));

  test('Escape clears the search', () => withHud(({ window, document }) => {
    window.renderGraph(VAULT);
    const box = document.getElementById('graphSearch');
    box.value = 'debug';
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    box.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(box.value, '');
    assert.deepEqual(Array.from(window.graphMatches()), []);
  }));

  test('typing in the search box must not trigger push-to-talk', () => withHud(({ window, document }) => {
    // Space is the talk key; typing a space in a search field must type a
    // space, not open the microphone.
    const sent = [];
    const box = document.getElementById('graphSearch');
    box.focus();
    const evt = new window.KeyboardEvent('keydown', { code: 'Space', bubbles: true, cancelable: true });
    Object.defineProperty(evt, 'target', { value: box });
    window.dispatchEvent(evt);
    assert.ok(!evt.defaultPrevented, 'the space must reach the input');
  }));
});

describe('search availability', () => {
  test('works before the GRAPH tab has ever been drawn', () => withHud(({ window }) => {
    // Regression: setGraphFilter read from state that only renderGraph filled,
    // so searching from the CORE tab reported "no matches" for a loaded vault.
    window.setGraphNodes(VAULT.nodes);            // data arrives...
    // ...with no renderGraph call at all
    assert.equal(window.setGraphFilter('debug'), 1);
  }));

  test('a query typed before the vault loads resolves once it arrives', () => withHud(({ window, document }) => {
    const box = document.getElementById('graphSearch');
    const count = document.getElementById('graphSearchCount');
    box.value = 'debug';
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.match(count.textContent, /no matches/);   // nothing loaded yet

    window.__hud.applyGraphNodes
      ? window.__hud.applyGraphNodes(VAULT.nodes)
      : window.setGraphNodes(VAULT.nodes);
    box.dispatchEvent(new window.Event('input', { bubbles: true }));
    assert.match(count.textContent, /1 match$/, 'the pending query should resolve');
  }));
});
