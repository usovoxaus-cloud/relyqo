export type PageState = 'loading' | 'ready' | 'failed';
export type PageEvent = 'start' | 'success' | 'error' | 'retry';

// Android may emit another load-start for its internal error document after
// onError. Only an explicit user retry/navigation may dismiss that error.
export function pageLoad(state: PageState, event: PageEvent): PageState {
  if (event === 'retry') return 'loading';
  if (event === 'error' || state === 'failed') return 'failed';
  return event === 'success' ? 'ready' : 'loading';
}
