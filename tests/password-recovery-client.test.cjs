/* Execute the shipped controller with a small DOM fixture; no browser or mail API. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('app/static/password-recovery.html', 'utf8');
const script = fs.readFileSync('app/static/password-recovery.js', 'utf8');

function page(hash = '') {
  const fields = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
    value: '', textContent: '', hidden: false, disabled: false, required: false,
    handlers: {}, button: { disabled: false },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    querySelector() { return this.button; },
    reset() {},
  }]));
  const location = { pathname: '/reset-password', hash };
  const requests = [];
  vm.runInNewContext(script, {
    document: { getElementById: id => fields[id] }, location,
    history: { replaceState(_state, _title, path) { assert.equal(path, '/reset-password'); location.hash = ''; } },
    window: { addEventListener() {} }, URLSearchParams,
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({ message: 'Пароль изменён.' }) };
    },
  });
  fields.newPassword.value = fields.confirmPassword.value = 'test-password-123';
  return { fields, location, requests, submit: () => fields.resetForm.handlers.submit({
    preventDefault() {}, currentTarget: fields.resetForm,
  }) };
}

test('legacy reset link removes URL secret and submits it without requiring an email or code', async () => {
  const token = 't'.repeat(43);
  const { fields, location, requests, submit } = page('#token=' + token);
  assert.equal(location.hash, '');
  assert.equal(fields.codeFields.hidden, true);
  assert.equal(fields.resetEmail.required, false);
  assert.equal(fields.resetCode.disabled, true);
  await submit();
  assert.deepEqual(requests, [{ url: '/v1/auth/reset-password', body: {
    token, new_password: 'test-password-123', confirm_password: 'test-password-123',
  } }]);
  assert.equal(fields.resetForm.hidden, true);
});

test('code entry uses email and code with no legacy token', async () => {
  const { fields, requests, submit } = page();
  assert.equal(fields.codeFields.hidden, false);
  assert.equal(fields.resetCode.required, true);
  fields.resetEmail.value = ' person@example.test ';
  fields.resetCode.value = '123456';
  await submit();
  assert.deepEqual(requests[0].body, { email: 'person@example.test', code: '123456',
    new_password: 'test-password-123', confirm_password: 'test-password-123' });
});

test('mismatched passwords never submit a recovery request', async () => {
  const { fields, requests, submit } = page();
  fields.confirmPassword.value = 'different-password';
  await submit();
  assert.equal(requests.length, 0);
  assert.match(fields.error.textContent, /не совпадают/);
});
