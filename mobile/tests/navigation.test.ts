import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ORIGIN, isInternalUrl, navigationKind, readVisitToken, tabForUrl, tabUrl, withLanguage, languageFromUrl } from '../src/navigation.ts';

test('only the exact HTTPS service origin stays inside the app', () => {
  assert.equal(isInternalUrl(ORIGIN + '/me?lang=ru'), true);
  for (const url of ['http://relyqo.onrender.com/me', 'https://relyqo.onrender.com.evil.test', 'https://relyqo.onrender.com@evil.test', 'https://user@relyqo.onrender.com', 'https://relyqo.onrender.com:444', '//relyqo.onrender.com', 'file:///data/a', 'javascript:alert(1)']) assert.equal(isInternalUrl(url), false, url);
});
test('external links require the OS flow and executable schemes are blocked', () => {
  assert.equal(navigationKind(ORIGIN + '/place?id=1'), 'internal');
  for (const url of ['https://maps.google.com', 'https://example.com', 'tel:+998901234567', 'mailto:help@example.com']) assert.equal(navigationKind(url), 'external');
  for (const url of ['javascript:alert(1)', 'data:text/html,<h1>x</h1>', 'intent://scan/#Intent;end', 'file:///tmp/a', 'content://media/a', 'https://user:pass@example.com', 'https://example.com\n']) assert.equal(navigationKind(url), 'blocked');
});
test('QR accepts a raw RELYQO token or an exact first-party visit URL', () => {
  const token = 'eyJicmFuY2hfaWQiOiJ0ZXN0In0.' + 'a'.repeat(43);
  assert.equal(readVisitToken(token), token);
  assert.equal(readVisitToken('  ' + token + '\n'), token);
  assert.equal(readVisitToken(ORIGIN + '/?token=' + token), token);
  assert.equal(readVisitToken(ORIGIN + '/consumer?token=' + token), token);
  for (const value of [ORIGIN + '/me?token=' + token, 'https://evil.test/?token=' + token, 'http://relyqo.onrender.com/?token=' + token, ORIGIN + '/?token=' + token + '&token=' + token, 'not a visit', 'x'.repeat(4097), '<script>alert(1)</script>', 'a'.repeat(40) + '.' + 'b'.repeat(42)]) assert.equal(readVisitToken(value), null, value.slice(0, 100));
});
test('language changes preserve organization and recovery URL parameters', () => {
  const url = ORIGIN + '/place?object_key=manual%3A123#reviews';
  const next = withLanguage(url, 'uz');
  assert.equal(new URL(next).searchParams.get('object_key'), 'manual:123');
  assert.equal(new URL(next).hash, '#reviews');
  assert.equal(languageFromUrl(next), 'uz');
  assert.equal(languageFromUrl('https://evil.test/?lang=uz'), null);
  assert.equal(withLanguage('https://evil.test/', 'ru'), tabUrl('search', 'ru'));
});
test('tab matching keeps details and role-specific login screens accessible', () => {
  assert.equal(tabForUrl(ORIGIN + '/nearby'), 'search');
  assert.equal(tabForUrl(ORIGIN + '/place?id=1'), 'search');
  assert.equal(tabForUrl(ORIGIN + '/me/rating?id=1'), 'account');
  assert.equal(tabForUrl(ORIGIN + '/business-owner'), 'account');
  assert.equal(tabForUrl(ORIGIN + '/admin'), 'account');
  assert.equal(tabForUrl(ORIGIN + '/rankings'), 'top');
  assert.equal(tabForUrl(ORIGIN + '/'), 'qr');
});
