import { ORIGIN } from './navigation.ts';

// This bridge only adapts presentation and requests a scanner. It cannot log in,
// read cookies or grant a role. Credentials stay in the first-party WebView.
export const MOBILE_BRIDGE = `
(function () {
  if (location.origin !== ${JSON.stringify(ORIGIN)}) return;
  if (!document.getElementById('relyqo-native-style')) {
    var style = document.createElement('style');
    style.id = 'relyqo-native-style';
    style.textContent = '.languageBar,main>header.top,main>header.homeHeader{display:none!important} body{padding-top:0!important} main.shell,main{padding-top:14px!important} .page-index .heroCard{display:none!important} input,select,textarea{font-size:16px!important} .page-nearby .results{height:auto!important;max-height:none!important}';
    document.head.appendChild(style);
  }
  if (!window.__relyqoNativeBridge) {
    window.__relyqoNativeBridge = true;
    document.addEventListener('click', function (event) {
      if (event.target.closest && event.target.closest('#startCamera')) {
        event.preventDefault(); event.stopImmediatePropagation();
        window.ReactNativeWebView.postMessage(JSON.stringify({type:'scan'}));
      }
    }, true);
  }
  window.ReactNativeWebView.postMessage(JSON.stringify({type:'ready',language:document.documentElement.lang}));
})(); true;
`;

export function deliverQrScript(token: string): string {
  // JSON serialization prevents scanned text becoming executable JavaScript.
  return `(function () {
    if (location.origin !== ${JSON.stringify(ORIGIN)} || !['/', '/consumer'].includes(location.pathname)) return;
    var input = document.getElementById('token'), button = document.getElementById('verify');
    if (!input || !button || button.disabled) return;
    input.value = ${JSON.stringify(token)};
    input.dispatchEvent(new Event('input', {bubbles:true}));
    button.click();
  })(); true;`;
}
