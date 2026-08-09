/* Vault and service-health panels. Both used to display hardcoded values that
 * looked live -- "Open threads: 3" and "7 online" were true of nothing. */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, realHudMarkup } from './hud-dom.mjs';

function withHud(fn) {
  const mod = loadModule(['core.js', 'graph.js', 'wave.js', 'hud.js'], realHudMarkup());
  try { fn(mod); } finally { mod.dom.window.close(); }
}

describe('vault panel', () => {
  test('shows real counts and the note that was actually edited last', () => withHud(({ window, document }) => {
    window.__hud.applyVault({
      type: 'vault', notes: 23, links: 71, folders: 7,
      lastNote: 'Debug Log', lastEditedMs: Date.now() - 120000,
    });
    const text = document.getElementById('vaultList').textContent;
    assert.match(text, /Notes: 23/);
    assert.match(text, /Links: 71/);
    assert.match(text, /Debug Log/);
    assert.match(text, /2m ago/);
    // the placeholders this replaced
    assert.doesNotMatch(text, /Open threads: 3/);
  }));

  test('an empty vault says so rather than rendering blanks', () => withHud(({ window, document }) => {
    window.__hud.applyVault({ type: 'vault' });
    assert.match(document.getElementById('vaultList').textContent, /vault empty/);
  }));

  test('relative times read sensibly across scales', () => withHud(({ window }) => {
    const { ago } = window.__hud;
    const now = Date.now();
    assert.equal(ago(now - 5000), 'just now');
    assert.equal(ago(now - 5 * 60000), '5m ago');
    assert.equal(ago(now - 3 * 3600000), '3h ago');
    assert.equal(ago(now - 2 * 86400000), '2d ago');
    assert.equal(ago(now + 10000), 'just now', 'clock skew must not print a negative age');
  }));
});

describe('service health panel', () => {
  test('a service that has never reported does not claim to be fine', () => withHud(({ document }) => {
    const rows = document.querySelectorAll('#serviceList li');
    assert.ok(rows.length >= 5, 'every service gets a row');
    for (const row of rows) {
      const dot = row.querySelector('.dot');
      assert.ok(!dot.classList.contains('online'), 'unknown must not render as online');
      assert.equal(row.querySelector('.svcstate').textContent, '—');
    }
  }));

  test('reflects online, offline and error states per service', () => withHud(({ window, document }) => {
    const st = window.__hud.applyServiceStatus;
    st({ service: 'ears', state: 'online' });
    st({ service: 'voice', state: 'offline', detail: 'no key' });
    st({ service: 'brain', state: 'error', detail: 'claude exited 1' });

    const row = (name) => document.querySelector(`#serviceList li[data-service="${name}"]`);
    assert.ok(row('ears').querySelector('.dot').classList.contains('online'));
    assert.ok(row('voice').querySelector('.dot').classList.contains('offline'));
    assert.ok(row('brain').querySelector('.dot').classList.contains('error'));
    assert.equal(row('ears').querySelector('.svcstate').textContent, 'online');
    // The reason is what actually helps. It moved from a native title= to
    // the custom tooltip, which is where it must now appear.
    row('voice').dispatchEvent(new window.MouseEvent('mouseenter'));
    assert.match(document.getElementById('svcTip').textContent, /no key/);
    row('brain').dispatchEvent(new window.MouseEvent('mouseenter'));
    assert.match(document.getElementById('svcTip').textContent, /claude exited 1/);
  }));

  test('recovery replaces a previous failure rather than stacking', () => withHud(({ window, document }) => {
    const st = window.__hud.applyServiceStatus;
    st({ service: 'vault', state: 'offline', detail: 'obsidian closed' });
    st({ service: 'vault', state: 'online' });
    const dot = document.querySelector('#serviceList li[data-service="vault"] .dot');
    assert.ok(dot.classList.contains('online'));
    assert.ok(!dot.classList.contains('offline'), 'a stale failure class must be cleared');
  }));

  test('an unknown service name is ignored, not thrown on', () => withHud(({ window }) => {
    assert.doesNotThrow(() => window.__hud.applyServiceStatus({ service: 'nope', state: 'online' }));
  }));
});

describe('service tooltip', () => {
  test('explains what the service is, not just its state', () => withHud(({ window, document }) => {
    window.__hud.applyServiceStatus({ service: 'ears', state: 'online' });
    const row = document.querySelector('#serviceList li[data-service="ears"]');
    row.dispatchEvent(new window.MouseEvent('mouseenter'));

    const tip = document.getElementById('svcTip');
    assert.ok(!tip.classList.contains('hide'), 'tooltip should be visible on hover');
    const text = tip.textContent;
    assert.match(text, /EARS/);
    assert.match(text, /faster-whisper/, 'must say what the service actually is');
    assert.match(text, /online/);
    // the old native tooltip only repeated the row's own text
    assert.ok(text.length > 40, 'a tooltip that only repeats the row is not worth hovering');
  }));

  test('surfaces the failure reason when there is one', () => withHud(({ window, document }) => {
    window.__hud.applyServiceStatus({
      service: 'calendar', state: 'offline', detail: 'not authorized -- run scripts/gcal_auth.py',
    });
    document.querySelector('#serviceList li[data-service="calendar"]')
      .dispatchEvent(new window.MouseEvent('mouseenter'));
    assert.match(document.getElementById('svcTip').textContent, /gcal_auth\.py/);
  }));

  test('says so plainly when a service has never reported', () => withHud(({ window, document }) => {
    document.querySelector('#serviceList li[data-service="voice"]')
      .dispatchEvent(new window.MouseEvent('mouseenter'));
    assert.match(document.getElementById('svcTip').textContent, /has not reported yet/);
  }));

  test('hides again on mouseleave', () => withHud(({ window, document }) => {
    const row = document.querySelector('#serviceList li[data-service="brain"]');
    row.dispatchEvent(new window.MouseEvent('mouseenter'));
    assert.ok(!document.getElementById('svcTip').classList.contains('hide'));
    row.dispatchEvent(new window.MouseEvent('mouseleave'));
    assert.ok(document.getElementById('svcTip').classList.contains('hide'));
  }));

  test('stays on screen instead of running off the right edge', () => withHud(({ window, document }) => {
    window.__hud.applyServiceStatus({ service: 'vault', state: 'online' });
    const row = document.querySelector('#serviceList li[data-service="vault"]');
    row.dispatchEvent(new window.MouseEvent('mouseenter'));
    const tip = document.getElementById('svcTip');
    assert.ok(parseFloat(tip.style.left) >= 8, 'must not be positioned off the left edge');
    assert.ok(parseFloat(tip.style.top) >= 8, 'must not be positioned above the viewport');
  }));
});
