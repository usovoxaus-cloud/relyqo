import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pageLoad } from '../src/page-load.ts';
import type { PageState } from '../src/page-load.ts';

test('Android internal error-page events cannot restart the spinner after network failure', () => {
  let state: PageState = 'loading';
  for (const event of ['error', 'start', 'success', 'start'] as const) {
    state = pageLoad(state, event);
    assert.equal(state, 'failed');
  }
});
test('explicit retry and back navigation allow a successful page to recover', () => {
  let state: PageState = 'failed';
  for (const event of ['retry', 'start', 'success'] as const) state = pageLoad(state, event);
  assert.equal(state, 'ready');
});
test('normal document navigation still shows loading and retry failure stays visible', () => {
  assert.equal(pageLoad('ready', 'start'), 'loading');
  assert.equal(pageLoad(pageLoad('failed', 'retry'), 'error'), 'failed');
});
