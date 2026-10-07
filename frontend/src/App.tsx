import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, message, type Board, type Pin, type PinPage, type User } from './api';
import { AuthForm, BoardForm, UploadForm } from './Forms';
import Closeup from './Closeup';

type View = 'discover' | 'uploads' | 'boards';
type Form = 'auth' | 'upload' | 'board' | null;
const hashPin = () => location.hash.startsWith('#pin/') ? location.hash.slice(5) : null;

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>('discover');
  const [boards, setBoards] = useState<Board[]>([]);
  const [selectedBoard, setSelectedBoard] = useState<Board | null>(null);
  const [pins, setPins] = useState<Pin[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState<Form>(null);
  const [pinId, setPinId] = useState(hashPin);
  const requestNumber = useRef(0);
  const endpoint = selectedBoard ? `/boards/${selectedBoard.id}/pins` : view === 'uploads' ? '/pins/mine' : '/pins';

  const refreshBoards = useCallback(async () => {
    try { setBoards(await api<Board[]>('/boards')); } catch (error) { setError(message(error)); }
  }, []);
  useEffect(() => {
    let active = true;
    api<User>('/auth/me').then(user => { if (active) setUser(user); }).catch(error => {
      if (active && !(error instanceof ApiError && error.status === 401)) setError(message(error));
    });
    return () => { active = false; };
  }, []);
  useEffect(() => { if (user) void refreshBoards(); else setBoards([]); }, [user, refreshBoards]);
  useEffect(() => {
    const listener = () => setPinId(hashPin());
    addEventListener('hashchange', listener);
    return () => removeEventListener('hashchange', listener);
  }, []);

  const loadPins = useCallback(async (after: string | null = null, quiet = false) => {
    const number = ++requestNumber.current;
    if (!quiet) { setBusy(true); setError(''); }
    try {
      const page = await api<PinPage>(`${endpoint}${after ? `?cursor=${encodeURIComponent(after)}` : ''}`);
      if (requestNumber.current !== number) return;
      setPins(previous => after ? [...previous, ...page.items.filter(pin => !previous.some(p => p.id === pin.id))] : page.items);
      setCursor(page.next_cursor);
    } catch (error) { if (requestNumber.current === number) setError(message(error)); }
    finally { if (requestNumber.current === number) setBusy(false); }
  }, [endpoint]);
  useEffect(() => {
    setPins([]); setCursor(null);
    if (view !== 'boards' || selectedBoard) void loadPins();
    return () => { ++requestNumber.current; };
  }, [loadPins, view, selectedBoard]);
  useEffect(() => {
    const pending = pins.filter(pin => ['queued', 'processing', 'failed'].includes(pin.status));
    if (view !== 'uploads' || !pending.length) return;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const updates = await Promise.all(pending.map(pin => api<Pin>(`/pins/${pin.id}`)));
        if (active) setPins(previous => previous.map(pin => updates.find(update => update.id === pin.id) || pin));
      } catch (error) { if (active) setError(message(error)); }
    }, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [view, pins]);

  function navigate(next: View) {
    if (next !== 'discover' && !user) { setForm('auth'); return; }
    setView(next); setSelectedBoard(null); setError('');
  }
  function closePin() { history.replaceState(null, '', location.pathname + location.search); setPinId(null); }
  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); setUser(null); closePin(); navigate('discover'); }
    catch (error) { setError(message(error)); }
  }
  async function retry(pin: Pin) {
    try { await api(`/pins/${pin.id}/retry`, { method: 'POST' }); await loadPins(); }
    catch (error) { setError(message(error)); }
  }
  async function unsave(pin: Pin) {
    if (!selectedBoard) return;
    try {
      await api(`/boards/${selectedBoard.id}/pins/${pin.id}`, { method: 'DELETE' });
      await loadPins(); await refreshBoards();
    } catch (error) { setError(message(error)); }
  }
  const showBoards = view === 'boards' && !selectedBoard;
  const title = selectedBoard?.name || (view === 'uploads' ? 'Your creations.' : view === 'boards' ? 'Ideas, gathered.' : 'Find your next inspiration.');
  return <>
    <header className="header">
      <button className="brand" onClick={() => navigate('discover')} aria-label="Pinmorph home"><span className="brand-mark">p</span>pinmorph<span className="brand-dot">.</span></button>
      <nav aria-label="Main navigation">
        <button aria-current={view === 'discover' ? 'page' : undefined} onClick={() => navigate('discover')}>Discover</button>
        <button aria-current={view === 'boards' ? 'page' : undefined} onClick={() => navigate('boards')}>My boards</button>
        {user && <button aria-current={view === 'uploads' ? 'page' : undefined} onClick={() => navigate('uploads')}>Uploads</button>}
      </nav>
      <div className="account">
        <button className="primary compact" onClick={() => setForm(user ? 'upload' : 'auth')}>+ Create pin</button>
        {user ? <><span className="user-name">{user.display_name}</span><button className="text-button" onClick={logout}>Sign out</button></>
          : <button className="text-button" onClick={() => setForm('auth')}>Sign in</button>}
      </div>
    </header>
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">{view === 'discover' ? 'A little curiosity goes a long way' : 'Your corner of inspiration'}</p>
          {selectedBoard && <button className="text-button back" onClick={() => setSelectedBoard(null)}>← All boards</button>}
          <h1>{title}</h1><p className="muted">{view === 'discover' ? 'Explore the collection. Keep the things you love.'
            : view === 'uploads' ? 'Add something new. We’ll get your image ready in a moment.' : 'A home for everything that catches your eye.'}</p></div>
        {view === 'boards' && <button className="secondary" onClick={() => setForm('board')}>+ New board</button>}
      </div>
      {error && <div className="error banner" role="alert">{error}<button className="text-button" onClick={() => { if (showBoards) void refreshBoards(); else void loadPins(); }}>Try again</button></div>}
      {showBoards ? <div className="boards-grid">
        {boards.map(board => <button className="board-card" key={board.id} onClick={() => setSelectedBoard(board)}>
          <div className="board-art"><span>✦</span></div><h2>{board.name}</h2><p>{board.pin_count} {board.pin_count === 1 ? 'pin' : 'pins'}</p>
        </button>)}
        {boards.length === 0 && <div className="empty"><h2>Room for your ideas.</h2><p>Create your first board, then save a few favorites.</p><button className="primary" onClick={() => setForm('board')}>Create a board</button></div>}
      </div> : <>
        <div className="masonry" aria-label="Pin collection" aria-busy={busy}>
          {pins.map(pin => <article className="pin-card" key={pin.id}>
            <button className="pin-open" onClick={() => { location.hash = `pin/${pin.id}`; }} aria-label={`Open ${pin.title}`}>
              <div className="pin-image" style={{ background: pin.dominant_color || '#ece7e1', aspectRatio: pin.width && pin.height ? `${pin.width}/${pin.height}` : '4/5' }}>
                {pin.thumbnail_url ? <img src={pin.thumbnail_url} alt={pin.title} loading="lazy" width={pin.width || undefined} height={pin.height || undefined} />
                  : <span className="processing">{pin.status === 'failed' ? 'Image processing failed' : 'Preparing your image…'}</span>}
                {pin.provenance === 'synthetic_demo' && <span className="demo-badge">Demo</span>}
              </div><h2>{pin.title}</h2>
            </button>
            {pin.status === 'failed' && <button className="text-button" onClick={() => retry(pin)}>Retry processing</button>}
            {selectedBoard && <button className="text-button" aria-label={`Remove ${pin.title} from board`} onClick={() => unsave(pin)}>Remove from board</button>}
          </article>)}
        </div>
        {!busy && !error && pins.length === 0 && <div className="empty"><span className="empty-star">✦</span><h2>{selectedBoard ? 'Make room for inspiration.' : 'Your inspiration starts here.'}</h2><p>{selectedBoard ? 'Explore the collection and save something you love.' : 'Add a pin to get the collection started.'}</p><button className="primary" onClick={() => selectedBoard ? navigate('discover') : setForm(user ? 'upload' : 'auth')}>{selectedBoard ? 'Explore pins' : 'Create a pin'}</button></div>}
        {busy && <p className="loading" role="status">Finding inspiration…</p>}
        {cursor && !busy && <div className="load-more"><button className="secondary" onClick={() => loadPins(cursor)}>Explore more</button></div>}
      </>}
    </main>
    <footer>Collect what moves you. <span>Made for curious minds.</span></footer>
    {pinId && <Closeup key={pinId} pinId={pinId} boards={boards} user={user} onClose={closePin}
      onAuth={() => setForm('auth')} onBoard={() => setForm('board')} onSaved={() => { void refreshBoards(); if (selectedBoard) void loadPins(); }} />}
    {form === 'auth' && <AuthForm onClose={() => setForm(null)} onUser={setUser} />}
    {form === 'upload' && <UploadForm onClose={() => setForm(null)} onPin={() => { navigate('uploads'); void loadPins(); }} />}
    {form === 'board' && <BoardForm onClose={() => setForm(null)} onBoard={board => { setBoards(previous => [board, ...previous]); }} />}
  </>;
}
