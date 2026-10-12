import { CONSUMER_PRESENTATION } from './consumer.ts';
import { ORIGIN } from './navigation.ts';

// This bridge only adapts presentation and requests a scanner. It cannot log in,
// read cookies or grant a role. Credentials stay in the first-party WebView.
export const MOBILE_BRIDGE = `
(function () {
  if (location.origin !== ${JSON.stringify(ORIGIN)}) return;
  // A service-worker fallback can fire onLoad without WebView's onHttpError.
  // Report it before 'ready', preserving the saved language and native retry.
  function connectionFailed() {
    window.ReactNativeWebView.postMessage(JSON.stringify({type:'connection-error'}));
  }
  if (document.body.dataset.relyqoOffline === 'true' || navigator.onLine === false) {
    connectionFailed();
    return;
  }
  if (!document.getElementById('relyqo-native-style')) {
    var style = document.createElement('style');
    style.id = 'relyqo-native-style';
    style.textContent = '.languageBar,main>header.top,main>header.homeHeader{display:none!important} body{padding-top:0!important} main.shell,main{padding-top:14px!important} .page-index .heroCard{display:none!important} input,select,textarea{font-size:16px!important} .page-nearby .results{height:auto!important;max-height:none!important}';
    document.head.appendChild(style);
  }
  ${CONSUMER_PRESENTATION}
  if (!window.__relyqoNativeBridge) {
    window.__relyqoNativeBridge = true;
    window.addEventListener('offline', connectionFailed);
    document.addEventListener('click', function (event) {
      if (event.target.closest && event.target.closest('#startCamera')) {
        event.preventDefault(); event.stopImmediatePropagation();
        window.ReactNativeWebView.postMessage(JSON.stringify({type:'scan'}));
      }
    }, true);
  }
  function ready(authenticated) {
    if (navigator.onLine === false) { connectionFailed(); return; }
    window.ReactNativeWebView.postMessage(JSON.stringify({type:'ready',language:document.documentElement.lang,authenticated:authenticated}));
  }
  var authenticated = document.body.dataset.consumerAuthenticated;
  if (authenticated === 'true' || authenticated === 'false') {
    ready(authenticated === 'true');
  } else {
    // Older/public documents may omit the marker even with a valid session.
    // Ask the existing first-party endpoint; absence is not a logout signal.
    if (!window.__relyqoNativeSessionCheck) {
      var controller = new AbortController();
      var timeout = setTimeout(function () { controller.abort(); }, 8000);
      window.__relyqoNativeSessionCheck = fetch('/v1/auth/me', {
        credentials:'same-origin', cache:'no-store', signal:controller.signal
      }).then(function (response) {
        return response.ok ? response.json() : null;
      }).then(function (user) { return !!user && user.role === 'CONSUMER'; })
        .catch(function () { return false; })
        .finally(function () { clearTimeout(timeout); window.__relyqoNativeSessionCheck = null; });
    }
    window.__relyqoNativeSessionCheck.then(ready);
  }
})(); true;
`;

export function deliverQrScript(token: string): string {
  // JSON serialization prevents scanned text becoming executable JavaScript.
  return `(function () {
    if (location.origin !== ${JSON.stringify(ORIGIN)} || !['/', '/consumer', '/rate'].includes(location.pathname)) return;
    var input = document.getElementById('token'), button = document.getElementById('verify');
    if (!input || !button || button.disabled) return;
    input.value = ${JSON.stringify(token)};
    input.dispatchEvent(new Event('input', {bubbles:true}));
    button.click();
  })(); true;`;
}
