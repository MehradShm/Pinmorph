import { useEffect, useState, type FormEvent } from 'react';
import { api, jsonBody, message, type Pin, type Product, type User } from './api';
import Modal from './Modal';
import { engagement } from './telemetry';

const availability = { in_stock: 'In stock', out_of_stock: 'Out of stock', preorder: 'Preorder', discontinued: 'Discontinued' };
export const productPrice = (product: Product) => new Intl.NumberFormat(undefined, { style: 'currency', currency: product.currency }).format(Number(product.price));

export function ProductDetails({ pin, servedPin, user, onPin }: { pin: Pin; servedPin?: Pin; user: User | null; onPin: (pin: Pin) => void }) {
  const [editing, setEditing] = useState(false);
  return <>
    {pin.product && <section className="product-details" aria-label="Product details">
      <p className="product-price">{productPrice(pin.product)} <small>{pin.product.currency}</small></p>
      <p>{availability[pin.product.availability]}</p>
      {['in_stock', 'preorder'].includes(pin.product.availability) && <a className="source" href={pin.product.merchant_url} target="_blank" rel="noopener noreferrer"
        onClick={() => { if (user) engagement(servedPin || pin, 'outbound_click'); }}>Visit shop ↗</a>}
    </section>}
    {user?.is_business && user.id === pin.owner_id && <button className="secondary" onClick={() => setEditing(true)}>{pin.product ? 'Edit product details' : 'Add product details'}</button>}
    {editing && <ProductEditor pin={pin} onClose={() => setEditing(false)} onPin={updated => { onPin(updated); setEditing(false); }} />}
  </>;
}

function ProductEditor({ pin, onClose, onPin }: { pin: Pin; onClose: () => void; onPin: (pin: Pin) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      onPin(await api<Pin>(`/pins/${pin.id}/product`, jsonBody({ price: form.get('price'), currency: form.get('currency'), availability: form.get('availability'), merchant_url: form.get('url') }, 'PUT')));
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true); setError('');
    try { await api(`/pins/${pin.id}/product`, { method: 'DELETE' }); onPin({ ...pin, product: null }); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title="Product details" onClose={onClose}>
    <form onSubmit={save}>
      <p>{pin.title}</p>
      <label>Price<input name="price" type="number" min="0.01" max="9999999999.99" step="0.01" defaultValue={pin.product?.price || ''} required /></label>
      <label>Currency<select aria-label="Currency" name="currency" defaultValue={pin.product?.currency || 'USD'}>{['USD', 'CAD', 'EUR', 'GBP', 'AUD', 'NZD', 'SEK', 'DKK'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Availability<select aria-label="Availability" name="availability" defaultValue={pin.product?.availability || 'in_stock'}>{Object.entries(availability).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Shop link<input name="url" type="url" maxLength={2000} defaultValue={pin.product?.merchant_url || ''} placeholder="https://your-shop.example/product" required /></label>
      <button className="primary" disabled={busy}>Save product</button>
      {pin.product && <button type="button" className="text-button" disabled={busy} onClick={remove}>Remove product details</button>}
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  </Modal>;
}

type BusinessProfile = { is_business: boolean; business_name: string | null; website: string | null };
export function Business({ user, onUser }: { user: User; onUser: (user: User) => void }) {
  const [profile, setProfile] = useState<BusinessProfile | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState('');
  useEffect(() => { let active = true; api<BusinessProfile>('/business/profile').then(value => { if (active) setProfile(value); }).catch(error => { if (active) setError(message(error)); }); return () => { active = false; }; }, []);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<BusinessProfile>('/business/profile', jsonBody({ business_name: form.get('business_name'), website: form.get('website') || null }, 'PUT'));
      setProfile(result); onUser({ ...user, is_business: true }); setSaved('Business profile saved.');
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="business-panel" aria-label="Business account">
    {profile && <form onSubmit={save}>
      <h2>{profile.is_business ? 'Your business profile' : 'Start a business account'}</h2>
      <p>Add product details to your own pins and see their activity. There are no fees or payments in this demo.</p>
      <label>Business name<input name="business_name" defaultValue={profile.business_name || user.display_name} required maxLength={120} /></label>
      <label>Business website<input name="website" type="url" maxLength={2000} defaultValue={profile.website || ''} /></label>
      <button className="primary" disabled={busy}>{profile.is_business ? 'Save business profile' : 'Enable business account'}</button>
      {saved && <p className="success" role="status">{saved}</p>}
    </form>}
    {error && <p className="error" role="alert">{error}</p>}
    {profile?.is_business && <><p>Open one of your pins in Uploads to add or edit its product details.</p><CreatorAnalytics /></>}
  </section>;
}

type Counts = { served: number; impressions: number; closeups: number; saves: number; outbound_clicks: number };
type Analytics = { totals: Counts; items: (Counts & { pin_id: string; title: string })[]; daily: (Counts & { day: string })[]; missing_days: string[]; next_cursor: string | null; latest_rollup_at: string | null };
const metrics: [keyof Counts, string][] = [['served', 'Pins returned'], ['impressions', 'Views'], ['closeups', 'Closeups'], ['saves', 'Save actions'], ['outbound_clicks', 'Outbound clicks']];
function CreatorAnalytics() {
  const [days, setDays] = useState(7);
  const [traffic, setTraffic] = useState('app');
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const end = new Date().toISOString().slice(0, 10);
  const start = new Date(Date.now() - (days - 1) * 86400000).toISOString().slice(0, 10);
  const params = new URLSearchParams({ start, end, traffic });
  useEffect(() => {
    let active = true; setBusy(true); setError('');
    api<Analytics>(`/business/analytics?${new URLSearchParams({ start, end, traffic })}`).then(value => { if (active) setData(value); })
      .catch(error => { if (active) setError(message(error)); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [start, end, traffic, revision]);
  async function refresh() {
    setBusy(true); setError('');
    try { await api(`/business/analytics/refresh?${new URLSearchParams({ start, end })}`, { method: 'POST' }); setRevision(value => value + 1); }
    catch (error) { setError(message(error)); setBusy(false); }
  }
  async function more() {
    setBusy(true); setError('');
    try { const next = await api<Analytics>(`/business/analytics?${params}&cursor=${data!.next_cursor}`); setData(previous => previous ? { ...next, items: [...previous.items, ...next.items] } : next); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section aria-label="Creator analytics">
    <h2>Your pin activity</h2>
    <div className="inline-actions">
      <label>Period<select aria-label="Period" value={days} disabled={busy} onChange={event => setDays(Number(event.target.value))}>{[7, 30, 90].map(day => <option key={day} value={day}>Last {day} days</option>)}</select></label>
      <label>Traffic<select aria-label="Traffic" value={traffic} disabled={busy} onChange={event => setTraffic(event.target.value)}><option value="app">App activity</option><option value="simulator">Simulator activity</option></select></label>
      <button className="secondary" disabled={busy} onClick={refresh}>Refresh analytics</button>
    </div>
    <p className="muted">UTC dates. Views require a visible pin; counts include your own activity. Imported purchases are excluded. Recent activity may take up to an hour to appear.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {data && <>
      {!!data.missing_days.length && <p role="status">Some days have not been calculated yet. Refresh analytics to complete this period.</p>}
      <div className="analytics-cards">{metrics.map(([key, label]) => <div key={key}><span>{label}</span><strong data-testid={`total-${key}`}>{data.totals[key]}</strong></div>)}</div>
      <p className="muted">{data.latest_rollup_at ? `Latest update: ${new Date(data.latest_rollup_at).toLocaleString()}` : 'Refresh analytics to build your first report.'}</p>
      <div className="analytics-table"><table><caption>Activity by pin</caption><thead><tr><th>Pin</th>{metrics.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>
        {data.items.map(pin => <tr key={pin.pin_id}><th scope="row">{pin.title}</th>{metrics.map(([key]) => <td key={key}>{pin[key]}</td>)}</tr>)}
      </tbody></table></div>
      {data.next_cursor && <button className="text-button" disabled={busy} onClick={more}>More analytics pins</button>}
      <details><summary>Daily activity</summary><div className="analytics-table"><table><thead><tr><th>UTC date</th>{metrics.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{data.daily.map(row => <tr key={row.day}><th scope="row">{row.day}</th>{metrics.map(([key]) => <td key={key}>{row[key]}</td>)}</tr>)}</tbody></table></div></details>
    </>}
  </section>;
}

export type AdLayout = { enabled: boolean; after_every: number; max_slots: number };
export function AdPlaceholder() {
  return <aside className="ad-placeholder" aria-label="Advertisement placeholder"><small>Advertisement placeholder</small><h2>Your brand could be here.</h2><p>A space for future sponsored content.</p></aside>;
}

export type ShopFilter = { q: string; currency: string };
export function ShopFilters({ value, onSearch }: { value: ShopFilter; onSearch: (filters: ShopFilter) => void }) {
  const [text, setText] = useState(value.q);
  const [currency, setCurrency] = useState(value.currency);
  useEffect(() => { setText(value.q); setCurrency(value.currency); }, [value]);
  return <form className="search-form" role="search" onSubmit={event => { event.preventDefault(); onSearch({ q: text.trim(), currency }); }}>
    <label>Search products<input type="search" value={text} onChange={event => setText(event.target.value)} maxLength={200} minLength={2} placeholder="Browse all or search a title" /></label>
    <label>Product currency<select aria-label="Product currency" value={currency} onChange={event => setCurrency(event.target.value)}><option value="">All currencies</option>{['USD', 'CAD', 'EUR', 'GBP', 'AUD', 'NZD', 'SEK', 'DKK'].map(code => <option key={code}>{code}</option>)}</select></label>
    <button className="primary">Find products</button>
  </form>;
}
