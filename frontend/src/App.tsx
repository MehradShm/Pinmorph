import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, jsonBody, message, type Board, type Pin, type PinPage, type Section, type User } from './api';
import { AuthForm, BoardForm, UploadForm } from './Forms';
import Closeup from './Closeup';
import SearchBar, { type Search } from './SearchBar';
import { Activity, People, ProfileDialog } from './Social';
import BoardTools from './BoardTools';
import { ImportForm, LensForm, Settings, Moderation } from './Extensions';
import { pagePins, ViewedPin } from './telemetry';
import type { FeedPage } from './api';

type View = 'discover' | 'uploads' | 'boards' | 'people' | 'activity' | 'following' | 'lens' | 'settings' | 'moderation';
type Form = 'auth' | 'upload' | 'board' | 'import' | null;
const hashPin = () => location.hash.startsWith('#pin/') ? location.hash.slice(5) : null;

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>('discover');
  const [boards, setBoards] = useState<Board[]>([]);
  const [selectedBoard, setSelectedBoard] = useState<Board | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [sectionId, setSectionId] = useState('');
  const [search, setSearch] = useState<Search>({ q: '', provenance: '' });
  const [profileId, setProfileId] = useState<string | null>(null);
  const [pins, setPins] = useState<Pin[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState<Form>(null);
  const [selectedPin, setSelectedPin] = useState<Pin | null>(null);
  const [onboarding, setOnboarding] = useState(false);
  const [pinId, setPinId] = useState(hashPin);
  const requestNumber = useRef(0);
  const searchParams = new URLSearchParams({ q: search.q, ...(search.provenance ? { provenance: search.provenance } : {}) });
  const endpoint = selectedBoard ? `/boards/${selectedBoard.id}/pins${sectionId ? `?section_id=${sectionId}` : ''}`
    : view === 'following' ? '/feed/following' : view === 'uploads' ? '/pins/mine' : search.q ? `/search/pins?${searchParams}` : user ? '/feed' : '/pins';

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
  useEffect(() => { if (user) { void refreshBoards(); api<{ onboarding_complete: boolean }>('/settings').then(prefs => setOnboarding(!prefs.onboarding_complete)).catch(() => {}); } else { setBoards([]); setOnboarding(false); } }, [user, refreshBoards]);
  useEffect(() => {
    const listener = () => setPinId(hashPin());
    addEventListener('hashchange', listener);
    return () => removeEventListener('hashchange', listener);
  }, []);

  const loadPins = useCallback(async (after: string | null = null, quiet = false) => {
    const number = ++requestNumber.current;
    if (!quiet) { setBusy(true); setError(''); }
    try {
      const page = await api<PinPage | FeedPage>(`${endpoint}${after ? `${endpoint.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(after)}` : ''}`);
      if (requestNumber.current !== number) return;
      setPins(previous => after ? [...previous, ...pagePins(page).filter(pin => !previous.some(p => p.id === pin.id))] : pagePins(page));
      setCursor(page.next_cursor);
    } catch (error) { if (requestNumber.current === number) setError(message(error)); }
    finally { if (requestNumber.current === number) setBusy(false); }
  }, [endpoint, user?.id]);
  useEffect(() => {
    setPins([]); setCursor(null);
    if ((view === 'discover' || view === 'uploads' || view === 'following') || selectedBoard) void loadPins();
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
    if (!['discover', 'people'].includes(next) && !user) { setForm('auth'); return; }
    setView(next); setSelectedBoard(null); setSectionId(''); setSections([]); setSearch({ q: '', provenance: '' }); setError('');
  }
  function closePin() { setSelectedPin(null); history.replaceState(null, '', location.pathname + location.search); setPinId(null); }
  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); setUser(null); setProfileId(null); closePin(); navigate('discover'); }
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
  async function moveSection(pin: Pin, value: string) {
    if (!selectedBoard || !value) return;
    try {
      await api(`/boards/${selectedBoard.id}/pins/${pin.id}/section`, jsonBody({ section_id: value === '_none' ? null : value }, 'PUT'));
      await loadPins();
    } catch (error) { setError(message(error)); }
  }
  function openBoard(board: Board) {
    setSelectedBoard(board); setSectionId(''); setSections([]); setView('boards'); setProfileId(null); setError('');
  }
  function openProfile(id: string) { closePin(); setProfileId(id); }
  const showBoards = view === 'boards' && !selectedBoard;
  const title = selectedBoard?.name || (view === 'uploads' ? 'Your creations.' : view === 'boards' ? 'Ideas, gathered.'
    : view === 'lens' ? 'Follow your curiosity.' : view === 'settings' ? 'Make it yours.' : view === 'moderation' ? 'Review reports.' : view === 'following' ? 'From people you follow.' : view === 'people' ? 'Find your people.' : view === 'activity' ? 'Your latest activity.' : 'Find your next inspiration.');
  return <>
    <header className="header">
      <button className="brand" onClick={() => navigate('discover')} aria-label="Pinmorph home"><span className="brand-mark">p</span>pinmorph<span className="brand-dot">.</span></button>
      <nav aria-label="Main navigation">
        <button aria-current={view === 'discover' ? 'page' : undefined} onClick={() => navigate('discover')}>Discover</button>
        <button aria-current={view === 'boards' ? 'page' : undefined} onClick={() => navigate('boards')}>My boards</button>
        <button aria-current={view === 'people' ? 'page' : undefined} onClick={() => navigate('people')}>People</button>
        {user && <><button aria-current={view === 'following' ? 'page' : undefined} onClick={() => navigate('following')}>Following</button>
          <button aria-current={view === 'lens' ? 'page' : undefined} onClick={() => navigate('lens')}>Lens</button></>}
        {user && <button aria-current={view === 'uploads' ? 'page' : undefined} onClick={() => navigate('uploads')}>Uploads</button>}
        {user && <><button aria-current={view === 'activity' ? 'page' : undefined} onClick={() => navigate('activity')}>Activity</button>
          <button onClick={() => openProfile(user.id)}>My profile</button>
          <button onClick={() => navigate('settings')}>Settings</button>
          {user.is_moderator && <button onClick={() => navigate('moderation')}>Moderation</button>}</>}
      </nav>
      <div className="account">
        <button className="primary compact" onClick={() => setForm(user ? 'upload' : 'auth')}>+ Create pin</button>
        {user ? <><span className="user-name">{user.display_name}</span><button className="text-button" onClick={logout}>Sign out</button></>
          : <button className="text-button" onClick={() => setForm('auth')}>Sign in</button>}
      </div>
    </header>
    <main>
      {onboarding && view === 'discover' && <aside className="onboarding-banner"><span>Choose interests to shape your feed.</span><button className="text-button" onClick={() => navigate('settings')}>Choose interests</button><button className="text-button" onClick={() => { void api('/settings', jsonBody({ interests: [], onboarding_complete: true, email_digest: false }, 'PUT')).then(() => setOnboarding(false)).catch(e => setError(message(e))); }}>Skip for now</button></aside>}
      <div className="page-heading">
        <div><p className="eyebrow">{view === 'discover' ? 'A little curiosity goes a long way' : 'Your corner of inspiration'}</p>
          {selectedBoard && <button className="text-button back" onClick={() => navigate(user ? 'boards' : 'people')}>← {user ? 'All boards' : 'People'}</button>}
          <h1>{title}</h1><p className="muted">{view === 'discover' ? 'Explore the collection. Keep the things you love.'
            : view === 'uploads' ? 'Add something new. We’ll get your image ready in a moment.' : 'A home for everything that catches your eye.'}</p></div>
        {user && <button className="secondary" onClick={() => setForm('import')}>Import image</button>}
        {view === 'boards' && user && <button className="secondary" onClick={() => setForm('board')}>+ New board</button>}
      </div>
      {view === 'discover' && <SearchBar value={search} onSearch={setSearch} />}
      {selectedBoard && <BoardTools board={selectedBoard} user={user} sections={sections} selectedSection={sectionId}
        onSections={setSections} onSection={setSectionId} onBoard={board => { setSelectedBoard(board); setBoards(previous => previous.map(row => row.id === board.id ? board : row)); }} />}
      {error && <div className="error banner" role="alert">{error}<button className="text-button" onClick={() => { if (showBoards) void refreshBoards(); else void loadPins(); }}>Try again</button></div>}
      {view === 'settings' ? <Settings onSaved={() => setOnboarding(false)} /> : view === 'moderation' && user ? <Moderation user={user} /> : view === 'people' ? <People onProfile={openProfile} /> : view === 'activity' ? <Activity onProfile={openProfile} /> : showBoards ? <div className="boards-grid">
        {boards.map(board => <button className="board-card" key={board.id} onClick={() => openBoard(board)}>
          <div className="board-art"><span>✦</span></div><h2>{board.name}</h2><p>{board.pin_count} {board.pin_count === 1 ? 'pin' : 'pins'} · {board.is_secret ? 'Secret' : 'Public'}</p>
        </button>)}
        {boards.length === 0 && <div className="empty"><h2>Room for your ideas.</h2><p>Create your first board, then save a few favorites.</p><button className="primary" onClick={() => setForm('board')}>Create a board</button></div>}
      </div> : <>
        {view === 'lens' && <LensForm onPage={(page, append) => { setPins(old => append ? [...old, ...pagePins(page).filter(pin => !old.some(p => p.id === pin.id))] : pagePins(page)); setCursor(null); }} />}
        <div className="masonry" aria-label="Pin collection" aria-busy={busy}>
          {pins.map(pin => <ViewedPin pin={pin} key={pin.id}>
            <button className="pin-open" onClick={() => { setSelectedPin(pin); location.hash = `pin/${pin.id}`; }} aria-label={`Open ${pin.title}`}>
              <div className="pin-image" style={{ background: pin.dominant_color || '#ece7e1', aspectRatio: pin.width && pin.height ? `${pin.width}/${pin.height}` : '4/5' }}>
                {pin.thumbnail_url ? <img src={pin.thumbnail_url} alt={pin.title} loading="lazy" width={pin.width || undefined} height={pin.height || undefined} />
                  : <span className="processing">{pin.status === 'failed' ? 'Image processing failed' : pin.status === 'quarantined' ? 'Awaiting review' : pin.status === 'removed' ? 'Removed after review' : 'Preparing your image…'}</span>}
                {pin.provenance === 'synthetic_demo' && <span className="demo-badge">Demo</span>}
              </div><h2>{pin.title}</h2>
            </button>
            {pin.status === 'failed' && <button className="text-button" onClick={() => retry(pin)}>Retry processing</button>}
            {selectedBoard && user?.id === selectedBoard.owner_id && <>
              <button className="text-button" aria-label={`Remove ${pin.title} from board`} onClick={() => unsave(pin)}>Remove from board</button>
              {sections.length > 0 && <label>Move to section<select aria-label={`Move ${pin.title} to section`} value="" onChange={event => moveSection(pin, event.target.value)}>
                <option value="">Choose a section</option><option value="_none">No section</option>
                {sections.map(section => <option key={section.id} value={section.id}>{section.name}</option>)}
              </select></label>}
            </>}
          </ViewedPin>)}
        </div>
        {!busy && !error && pins.length === 0 && <div className="empty"><span className="empty-star">✦</span><h2>{search.q ? 'No matching pins.' : selectedBoard ? 'Make room for inspiration.' : 'Your inspiration starts here.'}</h2><p>{search.q ? 'Try different words or another collection.' : selectedBoard ? 'Explore the collection and save something you love.' : 'Add a pin to get the collection started.'}</p>{!search.q && <button className="primary" onClick={() => selectedBoard ? navigate('discover') : setForm(user ? 'upload' : 'auth')}>{selectedBoard ? 'Explore pins' : 'Create a pin'}</button>}</div>}
        {busy && <p className="loading" role="status">Finding inspiration…</p>}
        {cursor && !busy && <div className="load-more"><button className="secondary" onClick={() => loadPins(cursor)}>Explore more</button></div>}
      </>}
    </main>
    <footer>Collect what moves you. <span>Made for curious minds.</span></footer>
    {pinId && <Closeup key={pinId} pinId={pinId} servedPin={selectedPin?.id === pinId ? selectedPin : pins.find(pin => pin.id === pinId)}
      onRelated={pin => { setSelectedPin(pin); location.hash = `pin/${pin.id}`; }} boards={boards} user={user} onClose={closePin}
      onHidden={() => { setPins(old => old.filter(pin => pin.id !== pinId)); closePin(); }}
      onAuth={() => setForm('auth')} onBoard={() => setForm('board')} onProfile={openProfile} onSaved={() => { void refreshBoards(); if (selectedBoard) void loadPins(); }} />}
    {profileId && <ProfileDialog key={profileId} id={profileId} user={user} onClose={() => { setProfileId(null); if (view === 'discover') void loadPins(); }}
      onAuth={() => setForm('auth')} onBoard={openBoard} onEdited={name => setUser(previous => previous ? { ...previous, display_name: name } : null)}
      onBlocked={() => { setProfileId(null); navigate('discover'); void loadPins(); }} />}
    {form === 'auth' && <AuthForm onClose={() => setForm(null)} onUser={setUser} />}
    {form === 'upload' && <UploadForm onClose={() => setForm(null)} onPin={() => { navigate('uploads'); void loadPins(); }} />}
    {form === 'import' && <ImportForm onClose={() => setForm(null)} onPin={() => { navigate('uploads'); void loadPins(); }} />}
    {form === 'board' && <BoardForm onClose={() => setForm(null)} onBoard={board => { setBoards(previous => [board, ...previous]); }} />}
  </>;
}
