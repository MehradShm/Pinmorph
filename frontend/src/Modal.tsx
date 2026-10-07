import { useEffect, useRef, type ReactNode } from 'react';

export default function Modal({ title, children, onClose, wide = false }: {
  title: string; children: ReactNode; onClose: () => void; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} className={wide ? 'modal wide' : 'modal'} aria-label={title}
    onCancel={onClose} onClick={event => { if (event.target === ref.current) onClose(); }}>
    <button className="close" aria-label="Close dialog" onClick={onClose}>×</button>
    {children}
  </dialog>;
}
