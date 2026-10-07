import { useEffect, useRef, type ReactNode } from 'react';
import { api, jsonBody, type Pin, type PinPage, type FeedPage } from './api';

async function emit(payload: object) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try { await api('/events', { ...jsonBody(payload), keepalive: true }); return; }
    catch { if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 250 * 2 ** attempt)); }
  }
}
export function engagement(pin: Pin, type: 'closeup' | 'save' | 'outbound_click') {
  void emit({ kind: 'engagement', type, event_id: crypto.randomUUID(), pin_id: pin.id,
    ...(pin.served ? { request_id: pin.served.request_id, position: pin.served.position,
      ...(pin.served.impression_event_id ? { impression_event_id: pin.served.impression_event_id } : {}) } : {}) });
}
export function pagePins(page: PinPage | FeedPage): Pin[] {
  return page.items.map((row, index) => 'pin' in row
    ? { ...row.pin, served: { request_id: page.request_id, position: row.position } }
    : { ...row, ...('attributed' in page && page.attributed ? { served: { request_id: page.request_id, position: index } } : {}) });
}
export function ViewedPin({ pin, children }: { pin: Pin; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!pin.served || !ref.current) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let visible = false;
    const cancel = () => { if (timer) clearTimeout(timer); timer = undefined; };
    const schedule = () => {
      cancel();
      if (!visible || document.hidden || pin.served!.impression_event_id) return;
      timer = setTimeout(() => {
        const id = crypto.randomUUID(); pin.served!.impression_event_id = id;
        void emit({ kind: 'impression', event_id: id, pin_id: pin.id,
          request_id: pin.served!.request_id, position: pin.served!.position,
          view_rule_version: 'viewport:50pct:1000ms:v1' });
      }, 1000);
    };
    const observer = new IntersectionObserver(entries => {
      visible = entries[0].intersectionRatio >= 0.5; schedule();
    }, { threshold: [0, 0.5, 1] });
    observer.observe(ref.current);
    document.addEventListener('visibilitychange', schedule);
    return () => { cancel(); observer.disconnect(); document.removeEventListener('visibilitychange', schedule); };
  }, [pin]);
  return <article ref={ref} className="pin-card">{children}</article>;
}
