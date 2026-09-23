export const ORIGIN = 'https://relyqo.onrender.com';
export type Language = 'ru' | 'uz';
export type Tab = 'search' | 'qr' | 'top' | 'account';
const paths: Record<Tab, string> = { search: '/nearby', qr: '/', top: '/rankings', account: '/me' };

export function isInternalUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.origin === ORIGIN && !url.username && !url.password;
  } catch { return false; }
}

export function navigationKind(value: string): 'internal' | 'external' | 'blocked' {
  if (isInternalUrl(value)) return 'internal';
  try {
    const url = new URL(value);
    if (url.username || url.password || /[\r\n]/.test(value)) return 'blocked';
    if (['https:', 'http:', 'tel:', 'mailto:'].includes(url.protocol)) return 'external';
  } catch { /* Invalid and executable schemes never reach the OS. */ }
  return 'blocked';
}

export function tabUrl(tab: Tab, language: Language): string {
  return `${ORIGIN}${paths[tab]}?lang=${language}`;
}

export function withLanguage(value: string, language: Language): string {
  const url = new URL(isInternalUrl(value) ? value : tabUrl('search', language));
  url.searchParams.set('lang', language);
  return url.href;
}

export function tabForUrl(value: string): Tab {
  if (!isInternalUrl(value)) return 'search';
  const path = new URL(value).pathname;
  if (path === '/' || path === '/consumer') return 'qr';
  if (path === '/rankings') return 'top';
  if (['/me', '/recover', '/forgot-password', '/reset-password', '/account-security', '/admin', '/business-owner', '/owner'].some(p => path === p || path.startsWith(p + '/'))) return 'account';
  return 'search';
}

// Shape check only. Signature, expiry and one-time use remain server-side checks.
export function readVisitToken(value: string): string | null {
  if (value.length > 4096) return null;
  let token = value.trim();
  if (/^https?:/i.test(token)) {
    if (!isInternalUrl(token)) return null;
    const url = new URL(token);
    if (!['/', '/consumer'].includes(url.pathname)) return null;
    const tokens = url.searchParams.getAll('token');
    if (tokens.length !== 1) return null;
    token = tokens[0];
  }
  return /^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
}

export function languageFromUrl(value: string): Language | null {
  if (!isInternalUrl(value)) return null;
  const language = new URL(value).searchParams.get('lang');
  return language === 'ru' || language === 'uz' ? language : null;
}
