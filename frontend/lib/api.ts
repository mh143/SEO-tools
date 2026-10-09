// Thin fetch wrapper: same-origin /api, cookie session, CSRF double-submit header on unsafe methods.

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)rl_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export function errorMessage(detail: unknown, fallback = "Something went wrong."): string {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((d) => (typeof d === "string" ? d : (d as { msg?: string }).msg || JSON.stringify(d))).join("; ");
  if (typeof detail === "object" && detail !== null && "message" in detail) return String((detail as { message: string }).message);
  return fallback;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method || "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
    cache: "no-store",
  });
  let data: any = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : data;
    throw new ApiError(res.status, errorMessage(detail, `Request failed (${res.status})`), detail);
  }
  return data as T;
}

export const post = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const patch = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T = any>(path: string) => api<T>(path, { method: "DELETE" });
