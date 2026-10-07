export type User = { id: string; display_name: string; email: string };
export type Pin = {
  id: string; title: string; description: string; source_url: string | null;
  owner_id: string | null; provenance: string; status: string;
  processing_error: string | null; width: number | null; height: number | null;
  dominant_color: string | null; image_url: string | null; thumbnail_url: string | null;
};
export type Board = { id: string; name: string; pin_count: number };
export type PinPage = { items: Pin[]; next_cursor: string | null; request_id: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...options, credentials: 'same-origin' });
  } catch {
    throw new Error('Could not connect. Please try again.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail
      : typeof detail?.message === 'string' ? detail.message
      : Array.isArray(detail) ? detail.map((e: { msg: string }) => e.msg).join('. ')
      : 'Something went wrong. Please try again.';
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export function jsonBody(value: unknown, method = 'POST'): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) };
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
