/**
 * Client de l'API FastAPI.
 *
 * - Dans le navigateur : toujours via le relais du front (`/api/*`, rewrites de next.config.ts).
 *   Front et API ont la même origine : pas de CORS, et le cookie de session (httpOnly,
 *   SameSite=Lax) part tout seul. Le JavaScript ne voit jamais le jeton.
 * - Sur le serveur Next (pages publiques) : appel direct à API_URL, sans cookie.
 */
import { serverProxyHeader } from "@/lib/client-ip";
import { ApiError } from "@/lib/errors";

const SERVER_API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

function baseUrl(): string {
  return typeof window === "undefined" ? SERVER_API_URL : "/api";
}

interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;
  // Côté serveur (pages publiques), appel direct à l'API : il porte lui aussi le secret du relais.
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(typeof window === "undefined" ? serverProxyHeader() : {}),
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${baseUrl()}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    signal,
  });
  if (response.status === 204) return null as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : null;
    const retry = Number(response.headers.get("Retry-After"));
    throw new ApiError(response.status, detail, Number.isFinite(retry) && retry > 0 ? retry : null);
  }
  return data as T;
}
