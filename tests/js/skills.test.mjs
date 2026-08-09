/* Skills panel: repeatable workflows run by click, voice or schedule. */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { loadModule, realHudMarkup } from './hud-dom.mjs';

function withHud(fn) {
  const mod = loadModule(['core.js', 'graph.js', 'wave.js', 'hud.js'], realHudMarkup());
  try { fn(mod); } finally { mod.dom.window.close(); }
}

const SKILLS = [
  { id: '06 Skills/Morning Brief.md', name: 'Morning Brief', icon: '*', schedule: 'daily 07:00' },
  { id: '06 Skills/Vault Cleanup.md', name: 'Vault Cleanup', icon: '~', schedule: null },
];

describe('skills panel', () => {
  test('renders one row per skill', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    const rows = document.querySelectorAll('#skillList li');
    assert.equal(rows.length, 2);
    assert.match(rows[0].textContent, /Morning Brief/);
    assert.match(rows[0].textContent, /daily 07:00/);
    assert.match(rows[1].textContent, /Vault Cleanup/);
  }));

  test('an empty skill list renders a sensible empty message', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: [] });
    const text = document.getElementById('skillList').textContent;
    assert.match(text, /no skills/i);
  }));

  test('clicking a skill sends run_skill with its id', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    const row = document.querySelector('#skillList li[data-skill="06 Skills/Morning Brief.md"]');
    row.querySelector('.skillBtn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const sent = window.__sent.map((s) => JSON.parse(s));
    const msg = sent.find((m) => m.type === 'run_skill');
    assert.ok(msg, 'must send a run_skill message');
    assert.equal(msg.id, '06 Skills/Morning Brief.md');
  }));

  test('a running skill shows running state and cannot be clicked again', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    window.__hud.applySkillState({ type: 'skill', state: 'running', id: '06 Skills/Morning Brief.md', name: 'Morning Brief' });

    const row = document.querySelector('#skillList li[data-skill="06 Skills/Morning Brief.md"]');
    assert.match(row.textContent, /running/i);
    const btn = row.querySelector('.skillBtn');
    assert.ok(btn.disabled, 'the button must be disabled while running');

    window.__sent.length = 0;
    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const sent = window.__sent.map((s) => JSON.parse(s));
    assert.ok(!sent.some((m) => m.type === 'run_skill'), 'a disabled row must not send another run');
  }));

  test('an error state is visible', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    window.__hud.applySkillState({
      type: 'skill', state: 'error', id: '06 Skills/Morning Brief.md', detail: 'claude exited 1',
    });
    const row = document.querySelector('#skillList li[data-skill="06 Skills/Morning Brief.md"]');
    assert.ok(row.classList.contains('error'));
    assert.match(row.textContent, /claude exited 1/);
    // an error must not leave the row stuck unclickable
    assert.ok(!row.querySelector('.skillBtn').disabled);
  }));

  test('a busy state is visible and distinct from running', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    window.__hud.applySkillState({ type: 'skill', state: 'busy', id: '06 Skills/Vault Cleanup.md' });
    const row = document.querySelector('#skillList li[data-skill="06 Skills/Vault Cleanup.md"]');
    assert.ok(row.classList.contains('busy'));
    assert.match(row.textContent, /busy/i);
  }));

  test('done clears a previous running/error state', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    const id = '06 Skills/Morning Brief.md';
    window.__hud.applySkillState({ type: 'skill', state: 'running', id });
    window.__hud.applySkillState({ type: 'skill', state: 'done', id });
    const row = document.querySelector(`#skillList li[data-skill="${id}"]`);
    assert.ok(!row.classList.contains('running'));
    assert.ok(!row.querySelector('.skillBtn').disabled);
  }));

  test('a skill state message for an unknown id is ignored, not thrown on', () => withHud(({ window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    assert.doesNotThrow(() => window.__hud.applySkillState({ type: 'skill', state: 'running', id: 'nope.md' }));
  }));

  test('re-rendering the list preserves the ability to click a fresh row', () => withHud(({ document, window }) => {
    window.__hud.applySkills({ type: 'skills', skills: SKILLS });
    window.__hud.applySkills({ type: 'skills', skills: SKILLS }); // e.g. a periodic refresh with the same data
    const row = document.querySelector('#skillList li[data-skill="06 Skills/Vault Cleanup.md"]');
    row.querySelector('.skillBtn').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const sent = window.__sent.map((s) => JSON.parse(s));
    assert.ok(sent.some((m) => m.type === 'run_skill' && m.id === '06 Skills/Vault Cleanup.md'));
  }));
});
