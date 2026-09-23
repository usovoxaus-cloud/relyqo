import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runInNewContext } from 'node:vm';
import { deliverQrScript, MOBILE_BRIDGE } from '../src/bridge.ts';
import { ORIGIN } from '../src/navigation.ts';

function page(origin = ORIGIN, pathname = '/') {
  let clicks = 0;
  const input = { value: '', dispatchEvent() {} };
  const button = { disabled: false, click() { clicks++; } };
  const context = { location: { origin, pathname }, document: { getElementById: (id: string) => id === 'token' ? input : id === 'verify' ? button : null }, Event: class {} };
  return { context, input, button, clicks: () => clicks };
}

test('QR bridge fills the existing form and verifies once without navigating', () => {
  const p = page();
  runInNewContext(deliverQrScript('a'.repeat(30) + '.' + 'b'.repeat(43)), p.context);
  assert.equal(p.clicks(), 1);
  assert.equal(p.input.value, 'a'.repeat(30) + '.' + 'b'.repeat(43));
});
test('QR bridge cannot deliver codes to other origins, pages or a busy form', () => {
  for (const p of [page('https://evil.test'), page(ORIGIN, '/me')]) {
    runInNewContext(deliverQrScript('token'), p.context);
    assert.equal(p.clicks(), 0); assert.equal(p.input.value, '');
  }
  const p = page(); p.button.disabled = true;
  runInNewContext(deliverQrScript('token'), p.context);
  assert.equal(p.clicks(), 0);
});
test('scanned text is serialized as data, never evaluated', () => {
  const p = page();
  const text = '\";throw new Error("injected");\\\n<script>alert(1)</script>';
  runInNewContext(deliverQrScript(text), p.context);
  assert.equal(p.input.value, text);
});
test('presentation bridge does nothing on an external page', () => {
  runInNewContext(MOBILE_BRIDGE, { location: { origin: 'https://evil.test' } });
});
