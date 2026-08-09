/* The thinking indicator: it must appear while a turn runs and, crucially,
 * always clear afterwards. An indicator stuck on is worse than none -- it
 * would say "still working" forever and you'd stop trusting it. */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, realHudMarkup } from './hud-dom.mjs';

// The real page markup -- see realHudMarkup().

/* hud.js starts a requestAnimationFrame loop and a clock interval at load.
   jsdom keeps its event loop alive while those run, so a window that is not
   closed makes the test process hang forever instead of exiting. */
function withHud(fn) {
  const mod = loadModule(['core.js', 'graph.js', 'wave.js', 'hud.js'], realHudMarkup());
  try {
    fn(mod);
  } finally {
    mod.dom.window.close();
  }
}

describe('thinking indicator', () => {
  test('shows while a turn is running and hides when it finishes', () => withHud(({ window, document }) => {
    const box = document.getElementById('thinking');
    assert.ok(box.classList.contains('hide'), 'hidden before any turn');

    window.__hud.applyThinking({ type: 'thinking', active: true });
    assert.ok(!box.classList.contains('hide'), 'visible while thinking');

    window.__hud.applyThinking({ type: 'thinking', active: false });
    assert.ok(box.classList.contains('hide'), 'hidden once the turn ends');
  }));

  test('starts its elapsed counter at 0s', () => withHud(({ window, document }) => {
    window.__hud.applyThinking({ type: 'thinking', active: true });
    assert.equal(document.getElementById('thinkTime').textContent, '0s');
  }));

  test('a repeated start does not leave a second timer running', () => withHud(({ window, document }) => {
    // Two turns in a row must not stack intervals -- the counter would then
    // jump by 2s at a time and never stop after the first clear.
    window.__hud.applyThinking({ type: 'thinking', active: true });
    window.__hud.applyThinking({ type: 'thinking', active: true });
    window.__hud.applyThinking({ type: 'thinking', active: false });
    assert.ok(document.getElementById('thinking').classList.contains('hide'));
  }));
});
