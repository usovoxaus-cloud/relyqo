import { isConsumerUrl, isInternalUrl, ORIGIN } from './navigation.ts';

// Android WebMessageListener reports sourceOrigin, while iOS and Android's
// legacy bridge report a full URL. The injected main-frame script supplies its
// document URL separately so stale pages still cannot change the current UI.
export function bridgePageUrl(source: string, documentUrl: unknown, current: string): string | null {
  if (!isInternalUrl(source) || typeof documentUrl !== 'string' || documentUrl.length > 8192
    || !isConsumerUrl(documentUrl) || !isConsumerUrl(current)) return null;
  try {
    const page = new URL(documentUrl).href;
    const sender = new URL(source).href;
    if (page !== new URL(current).href) return null;
    if (sender !== ORIGIN + '/' && sender !== page) return null;
    return page;
  } catch { return null; }
}
