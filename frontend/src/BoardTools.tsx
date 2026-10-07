import { useEffect, useState } from 'react';
import { api, jsonBody, message, type Board, type Section, type User } from './api';

export default function BoardTools({ board, user, sections, selectedSection, onSections, onSection, onBoard }: {
  board: Board; user: User | null; sections: Section[]; selectedSection: string;
  onSections: (sections: Section[]) => void; onSection: (id: string) => void; onBoard: (board: Board) => void;
}) {
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const own = user?.id === board.owner_id;
  useEffect(() => {
    let active = true;
    api<Section[]>(`/boards/${board.id}/sections`).then(rows => { if (active) onSections(rows); })
      .catch(error => { if (active) setError(message(error)); });
    return () => { active = false; };
  }, [board.id, onSections]);
  async function privacy() {
    setBusy(true); setError('');
    try { onBoard(await api<Board>(`/boards/${board.id}`, jsonBody({ name: board.name, is_secret: !board.is_secret }, 'PUT'))); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function follow() {
    setBusy(true); setError('');
    try { await api(`/social/boards/${board.id}/follow`, { method: board.is_following ? 'DELETE' : 'PUT' }); onBoard({ ...board, is_following: !board.is_following }); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function addSection() {
    setBusy(true); setError('');
    try { const section = await api<Section>(`/boards/${board.id}/sections`, jsonBody({ name: name.trim() })); onSections([...sections, section]); setName(''); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function removeSection() {
    setBusy(true); setError('');
    try { await api(`/boards/${board.id}/sections/${selectedSection}`, { method: 'DELETE' }); onSections(sections.filter(section => section.id !== selectedSection)); onSection(''); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="board-tools" aria-label="Board settings">
    <div className="inline-actions"><span className="muted">{board.is_secret ? 'Secret board' : 'Public board'}</span>
      {own && <button className="secondary" disabled={busy} onClick={privacy}>{board.is_secret ? 'Make public' : 'Make secret'}</button>}
      {!own && user && <button className="secondary" disabled={busy} onClick={follow}>{board.is_following ? 'Unfollow board' : 'Follow board'}</button>}
    </div>
    <div className="inline-actions">
      <label>Board section<select value={selectedSection} onChange={event => onSection(event.target.value)}>
        <option value="">All pins</option>{sections.map(section => <option key={section.id} value={section.id}>{section.name}</option>)}
      </select></label>
      {own && selectedSection && <button className="text-button" disabled={busy} onClick={removeSection}>Delete section</button>}
    </div>
    {own && <form className="search-form" onSubmit={event => { event.preventDefault(); void addSection(); }}>
      <label>New section<input value={name} onChange={event => setName(event.target.value)} required maxLength={100} /></label>
      <button className="secondary" disabled={busy || !name.trim()}>Add section</button>
    </form>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
