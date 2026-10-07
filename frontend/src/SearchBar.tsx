import { useEffect, useState, type FormEvent } from 'react';
import { api, message } from './api';

export type Search = { q: string; provenance: string };

export default function SearchBar({ value, onSearch }: { value: Search; onSearch: (search: Search) => void }) {
  const [text, setText] = useState(value.q);
  const [provenance, setProvenance] = useState(value.provenance);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [error, setError] = useState('');
  useEffect(() => { setText(value.q); setProvenance(value.provenance); }, [value]);
  useEffect(() => {
    let active = true;
    setSuggestions([]); setError('');
    if (text.trim().length < 2) return;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ q: text.trim(), ...(provenance ? { provenance } : {}) });
      api<{ items: string[] }>(`/search/suggest?${params}`).then(result => { if (active) setSuggestions(result.items); })
        .catch(error => { if (active) setError(message(error)); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [text, provenance]);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSearch({ q: text.trim(), provenance });
  }
  return <div className="search-area">
    <form className="search-form" role="search" onSubmit={submit}>
      <label>Search pins<input type="search" value={text} onChange={event => setText(event.target.value)}
        placeholder="Try fashion, nature, or a title" minLength={2} maxLength={200} list="pin-search-suggestions" />
        <datalist id="pin-search-suggestions">{suggestions.map(title => <option key={title} value={title} />)}</datalist></label>
      <label>Collection<select aria-label="Collection" value={provenance} onChange={event => setProvenance(event.target.value)}>
        <option value="">All collections</option><option value="manual_upload">Community uploads</option>
        <option value="synthetic_demo">Demo collection</option><option value="hm">H&amp;M collection</option>
      </select></label>
      <button className="primary" disabled={text.trim().length < 2}>Search</button>
      {value.q && <button className="text-button" type="button" onClick={() => onSearch({ q: '', provenance: '' })}>Clear search</button>}
    </form>
    {error && <p className="error" role="alert">Suggestions unavailable: {error}</p>}
  </div>;
}
