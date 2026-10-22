export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Server nicht erreichbar (offline, Server down) - im Gegensatz zu einer Antwort mit Fehlerstatus. */
export class OfflineError extends Error {
  constructor() {
    super("Server nicht erreichbar");
  }
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
export const onUnauthorized = (fn: Listener) => {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
};

export interface ApiOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  /** 401 nicht als "Sitzung abgelaufen" melden (z. B. Login-Formular, Share-Links) */
  quiet401?: boolean;
}

async function raw(path: string, opts: ApiOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let response: Response;
  try {
    response = await fetch(path, { method: opts.method ?? "GET", headers, body, credentials: "same-origin" });
  } catch {
    throw new OfflineError();
  }
  if (response.status === 401 && !opts.quiet401) unauthorizedListeners.forEach((fn) => fn());
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* Antwort ohne JSON */
    }
    throw new ApiError(response.status, message);
  }
  return response;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const response = await raw(path, opts);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function download(path: string, filename: string): Promise<void> {
  const blob = await (await raw(path)).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export interface Fetched {
  blob: Blob;
  filename: string;
  headers: Headers;
}

function filenameFrom(response: Response, fallback: string): string {
  const header = response.headers.get("content-disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : fallback;
}

/** Datei per POST holen (Werkzeug-Export) und den vom Server vorgeschlagenen Namen mitliefern. */
export async function fetchFile(path: string, body: unknown, fallback = "export"): Promise<Fetched> {
  const response = await raw(path, { method: "POST", body });
  return { blob: await response.blob(), filename: filenameFrom(response, fallback), headers: response.headers };
}

export async function fetchGet(path: string, fallback = "datei"): Promise<Fetched> {
  const response = await raw(path);
  return { blob: await response.blob(), filename: filenameFrom(response, fallback), headers: response.headers };
}

export function saveBlob({ blob, filename }: Pick<Fetched, "blob" | "filename">): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e));
