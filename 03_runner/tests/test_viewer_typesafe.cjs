// Run with node tests/test_viewer_typesafe.cjs (standard library only).
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.join(__dirname, '../../05_viewer/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/\bboot\(\);\s*$/, '');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', checked: false, value: '', classList: { toggle() {}, contains() { return false; } },
    addEventListener() {}, querySelectorAll: () => [],
  });
  return elements.get(id);
};
const context = vm.createContext({
  document: { getElementById: element, body: element('body'), querySelectorAll: () => [] },
  localStorage: { getItem: () => null }, navigator: { language: 'en' },
  setInterval, clearInterval, console,
});
// Load the actual complete script, with only automatic network boot suppressed.
vm.runInContext(script, context);
vm.runInContext(`
  app.run = {kind: 'replay', config: {backend: 'typesafe'}};
  globalThis.fixture = {
    config: {chapter: 'ch01_the_hostage', backend: 'typesafe'},
    decisions: [{node_id: 'fish', context_shown: 'A fish',
      choices_shown: ['Save <fish>', 'Leave it'],
      choices_with_ids: [{id:'save',text:'Save <fish>'},{id:'leave',text:'Leave it'}],
      ai_choice_id: 'leave', ai_choice_text:'Leave it', ai_reasoning: null,
      ai_response_raw: 'RAW_RESPONSE_SHOULD_NOT_RENDER',
      decision_metadata: {kind:'typed_choice', probabilities:{save:0.2,leave:0.8},confidence:0.4},
      state_after: {}, latency_ms: 100}],
    ending: {},
  };
  globalThis.events = chapterToEvents(fixture);
  globalThis.node = {...events[1], id:'fish', decision:events[2]};
  updateNodeCard({index:1}, node);
`, context);
let rendered = element('card-1-fish').innerHTML;
assert.match(rendered, /20\.0%/);
assert.match(rendered, /80\.0%/);
assert.match(rendered, /40\.0%/);
assert.match(rendered, /Save &lt;fish&gt;/);
assert.match(rendered, /Choice probabilities/);
assert.doesNotMatch(rendered, /RAW_RESPONSE_SHOULD_NOT_RENDER|AI's reasoning/);
// Live events have the same payload but have not passed through replay conversion.
vm.runInContext(`
  node.decision = {choice_id:'leave', latency_ms:100,
    decision_metadata:fixture.decisions[0].decision_metadata, state_after:{}};
  updateNodeCard({index:1}, node);
`, context);
assert.equal(element('card-1-fish').innerHTML, rendered);
vm.runInContext(`uiLang='zh'; updateNodeCard({index:1}, node);`, context);
assert.match(element('card-1-fish').innerHTML, /决策置信度/);
// Legacy results still render their original rationale with no probability UI.
vm.runInContext(`
  delete fixture.decisions[0].decision_metadata;
  delete fixture.decisions[0].choices_with_ids;
  fixture.decisions[0].ai_reasoning='Legacy rationale';
  node = {...chapterToEvents(fixture)[1], id:'fish', decision:chapterToEvents(fixture)[2]};
  updateNodeCard({index:1}, node);
  app.meta={models:[{id:'jev',provider:'typesafe',configured:true}]};
  $('f-model').value='jev'; updateModelHint();
`, context);
assert.match(element('card-1-fish').innerHTML, /Legacy rationale/);
assert.doesNotMatch(element('card-1-fish').innerHTML, /决策置信度/);
assert.equal(element('f-temperature').disabled, true);
assert.match(element('temp-hint').textContent, /JEV/);
console.log('PASS: JEV live/replay, ordinal mapping, escaped text, bilingual display, legacy replay, temperature control');
