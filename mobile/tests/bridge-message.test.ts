import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bridgePageUrl } from '../src/bridge-message.ts';
import { ORIGIN } from '../src/navigation.ts';

const rating = ORIGIN + '/community-rate?lang=ru&object_key=manual%3Afixture';

test('modern Android origin-only and iOS/legacy full-URL events identify the same current rating page', () => {
  for (const source of [ORIGIN, ORIGIN + '/', rating]) {
    assert.equal(bridgePageUrl(source, rating, rating), rating);
  }
});

test('origin-only events from the previous page cannot restore its session or deliver a QR', () => {
  for (const current of [ORIGIN + '/welcome', ORIGIN + '/me', rating + '&lang=uz']) {
    assert.equal(bridgePageUrl(ORIGIN, rating, current), null);
  }
  assert.equal(bridgePageUrl(ORIGIN + '/welcome', rating, rating), null);
});

test('missing document URLs, foreign senders and management pages are rejected', () => {
  for (const source of ['https://evil.test', 'http://relyqo.onrender.com', 'https://user@relyqo.onrender.com']) {
    assert.equal(bridgePageUrl(source, rating, rating), null);
  }
  for (const claimed of [undefined, null, true, {}, 'invalid', ORIGIN + '/admin', 'https://evil.test', rating + 'x'.repeat(8192)]) {
    assert.equal(bridgePageUrl(ORIGIN, claimed, typeof claimed === 'string' ? claimed : rating), null);
  }
});

test('canonical URLs permit default HTTPS ports without accepting another document', () => {
  assert.equal(bridgePageUrl(ORIGIN, rating.replace('.com/', '.com:443/'), rating), rating);
});
