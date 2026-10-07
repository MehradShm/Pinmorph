import { useEffect, useState } from 'react';
import { api, message, type Board, type Pin, type User } from './api';
import Modal from './Modal';

export default function Closeup({ pinId, boards, user, onClose, onAuth, onBoard, onSaved }: {
  pinId: string; boards: Board[]; user: User | null; onClose: () => void;
  onAuth: () => void; onBoard: () => void; onSaved: () => void;
}) {
  const [pin, setPin] = useState<Pin | null>(null);
  const [boardId, setBoardId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState('');
  useEffect(() => {
    let active = true;
    api<Pin>(`/pins/${pinId}`).then(pin => { if (active) setPin(pin); })
      .catch(error => { if (active) setError(message(error)); });
    return () => { active = false; };
  }, [pinId]);
  useEffect(() => { if (!boardId && boards.length) setBoardId(boards[0].id); }, [boards, boardId]);
  async function save() {
    if (!user) { onAuth(); return; }
    if (!boardId) { onBoard(); return; }
    setBusy(true); setError('');
    try {
      await api(`/boards/${boardId}/pins/${pinId}`, { method: 'POST' });
      setSaved(`Saved to ${boards.find(board => board.id === boardId)?.name}`); onSaved();
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <Modal title={pin?.title || 'Pin detail'} onClose={onClose} wide>
    {pin ? <div className="closeup">
      <div className="closeup-image" style={{ background: pin.dominant_color || '#eee' }}>
        {pin.image_url ? <img src={pin.image_url} alt={pin.title} /> : <p>Image is {pin.status}.</p>}
      </div>
      <div className="closeup-info">
        <p className="eyebrow">{pin.provenance === 'synthetic_demo' ? 'Demo collection' : 'Worth a closer look'}</p>
        <h2>{pin.title}</h2><p className="description">{pin.description}</p>
        {pin.source_url && <a className="source" href={pin.source_url} target="_blank" rel="noopener noreferrer">Visit source ↗</a>}
        {pin.status === 'ready' && <div className="save-controls">
          {user && boards.length > 0 && <label>Save to board<select aria-label="Save to board" value={boardId}
            onChange={event => { setBoardId(event.target.value); setSaved(''); }}>
            {boards.map(board => <option key={board.id} value={board.id}>{board.name}</option>)}
          </select></label>}
          <button className="primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save pin'}</button>
          {user && <button className="text-button" onClick={onBoard}>+ Create a board</button>}
        </div>}
        {saved && <p className="success" role="status">{saved}</p>}
      </div>
    </div> : <p className="muted">{error ? 'Pin could not be opened.' : 'Loading pin…'}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}
