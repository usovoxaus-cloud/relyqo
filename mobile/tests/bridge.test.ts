import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runInNewContext } from 'node:vm';
import { readFileSync } from 'node:fs';
import { pageLoad } from '../src/page-load.ts';
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

test('an explicit server session marker is reported without an extra request', () => {
  for (const authenticated of ['false', 'true']) {
    const messages: string[] = [];
    runInNewContext(MOBILE_BRIDGE, {
      location: {origin: ORIGIN}, navigator: {onLine: true},
      document: {getElementById: () => ({}), documentElement: {lang: 'uz'}, body: {dataset: {consumerAuthenticated: authenticated}}},
      window: {__relyqoNativeBridge: true, ReactNativeWebView: {postMessage: (message: string) => messages.push(message)}}
    });
    assert.deepEqual(JSON.parse(messages[0]), {type:'ready', language:'uz', authenticated:authenticated === 'true'});
  }
});

function unmarkedPage(fetchSession: typeof fetch) {
  const p = networkPage(true);
  delete (p.context.document.body.dataset as {consumerAuthenticated?: string}).consumerAuthenticated;
  return {...p, context: {...p.context, fetch: fetchSession, AbortController, setTimeout, clearTimeout}};
}

async function flushBridge() { await new Promise(resolve => setImmediate(resolve)); }

test('an unmarked community rating page retains navigation for a signed-in consumer', async () => {
  const html = readFileSync(new URL('../../app/static/community-rate.html', import.meta.url), 'utf8');
  assert.match(html, /page-community-rate/);
  assert.doesNotMatch(html, /data-consumer-authenticated/);
  let requests = 0;
  const p = unmarkedPage(async (url, options) => {
    requests++;
    assert.equal(url, '/v1/auth/me');
    assert.equal(options?.credentials, 'same-origin');
    assert.equal(options?.cache, 'no-store');
    return Response.json({role:'CONSUMER', username:'test-only'});
  });
  runInNewContext(MOBILE_BRIDGE, p.context);
  runInNewContext(MOBILE_BRIDGE, p.context);
  assert.deepEqual(p.messages(), []); // Missing marker must not emit a premature logout.
  await flushBridge();
  assert.equal(requests, 1);
  assert.ok(p.messages().length > 0);
  for (const message of p.messages()) assert.deepEqual(message, {type:'ready', language:'uz', authenticated:true});
});

test('missing, expired, non-consumer and failed sessions never enable navigation', async () => {
  for (const response of [
    () => new Response('', {status:401}),
    () => Response.json({role:'RELYQO_ADMIN'}),
    () => Response.json({}),
    () => Response.json(null),
    () => new Response('invalid json'),
    () => { throw new Error('network failure'); },
  ]) {
    const p = unmarkedPage(async () => response());
    runInNewContext(MOBILE_BRIDGE, p.context);
    await flushBridge();
    assert.deepEqual(p.messages(), [{type:'ready', language:'uz', authenticated:false}]);
  }
});

test('a session check completing after disconnection cannot reopen native navigation', async () => {
  let complete!: (response: Response) => void;
  const p = unmarkedPage(() => new Promise(resolve => { complete = resolve; }));
  runInNewContext(MOBILE_BRIDGE, p.context);
  p.context.navigator.onLine = false;
  complete(Response.json({role:'CONSUMER'}));
  await flushBridge();
  assert.deepEqual(p.messages(), [{type:'connection-error'}]);
});

function networkPage(onLine: boolean | undefined, fallback = false) {
  const messages: string[] = [];
  const listeners: Record<string, () => void> = {};
  const context = {
    location: {origin: ORIGIN}, navigator: {onLine},
    document: {
      getElementById: () => ({}), documentElement: {lang: fallback ? 'ru' : 'uz'},
      body: {dataset: {relyqoOffline: fallback ? 'true' : undefined, consumerAuthenticated: 'true'}},
      addEventListener() {},
    },
    window: {
      addEventListener: (event: string, listener: () => void) => { assert.equal(listeners[event], undefined); listeners[event] = listener; },
      ReactNativeWebView: {postMessage: (message: string) => messages.push(message)},
    },
  };
  return {context, listeners, messages: () => messages.map(message => JSON.parse(message))};
}

test('service-worker fallback is a native error even when Wi-Fi reports online', async () => {
  type Navigation = {request: {mode: string; method: string}; respondWith: (response: Promise<Response>) => void};
  const handlers: Record<string, (event: Navigation) => void> = {};
  runInNewContext(readFileSync(new URL('../../app/static/sw.js', import.meta.url), 'utf8'), {
    self: {addEventListener: (type: string, handler: (event: Navigation) => void) => { handlers[type] = handler; }},
    fetch: () => Promise.reject(new Error('No internet')), Response,
  });
  let response: Promise<Response> | undefined;
  handlers.fetch({request: {mode: 'navigate', method: 'GET'}, respondWith: value => { response = value; }});
  assert.ok(response);
  const fallback = await response;
  assert.equal(fallback.status, 503);
  assert.equal(fallback.headers.get('Cache-Control'), 'no-store');
  assert.match(await fallback.text(), /data-relyqo-offline="true"/);
  const p = networkPage(true, true);
  runInNewContext(MOBILE_BRIDGE, p.context);
  // No 'ready' message carrying the fallback's Russian language or auth state.
  assert.deepEqual(p.messages(), [{type:'connection-error'}]);
  assert.equal(pageLoad(pageLoad('ready', 'error'), 'success'), 'failed');
});

test('old fallback without the marker is detected after all network interfaces are disabled', () => {
  const p = networkPage(false);
  runInNewContext(MOBILE_BRIDGE, p.context);
  assert.deepEqual(p.messages(), [{type:'connection-error'}]);
});

test('loss of connection after a loaded document reports an error once per event', () => {
  const p = networkPage(true);
  runInNewContext(MOBILE_BRIDGE, p.context);
  runInNewContext(MOBILE_BRIDGE, p.context);
  p.listeners.offline();
  assert.equal(p.messages().filter(message => message.type === 'connection-error').length, 1);
});

test('an unknown network state does not block a successfully loaded document', () => {
  const p = networkPage(undefined);
  runInNewContext(MOBILE_BRIDGE, p.context);
  assert.deepEqual(p.messages(), [{type:'ready', language:'uz', authenticated:true}]);
});
