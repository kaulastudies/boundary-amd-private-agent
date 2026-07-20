import { isIP } from "node:net";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8080";
const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_BODY_BYTES = 64 * 1024;

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
    return false;
  }
  return parts[0] === 10
    || parts[0] === 127
    || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
    || (parts[0] === 192 && parts[1] === 168)
    || (parts[0] === 169 && parts[1] === 254);
}

function isPrivateIpv6(hostname: string): boolean {
  const normalized = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return normalized === "::1"
    || normalized.startsWith("fc")
    || normalized.startsWith("fd")
    || /^fe[89ab]/.test(normalized);
}

export function validateBackendUrl(rawUrl: string): URL {
  const parsed = new URL(rawUrl);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error("unsupported backend URL scheme");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("backend URL must not contain credentials, query, or fragment");
  }
  if (parsed.pathname !== "/" && parsed.pathname !== "") {
    throw new Error("backend URL must not contain a path");
  }
  const hostname = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  const local = hostname === "localhost"
    || (isIP(hostname) === 4 && isPrivateIpv4(hostname))
    || (isIP(hostname) === 6 && isPrivateIpv6(hostname));
  if (!local) {
    throw new Error("backend URL must be local or private");
  }
  return parsed;
}

function timeoutMs(): number {
  const parsed = Number(process.env.BOUNDARY_BACKEND_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
  return Number.isFinite(parsed) && parsed >= 1_000 && parsed <= 120_000
    ? parsed
    : DEFAULT_TIMEOUT_MS;
}

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ code, message }, { status });
}

function sanitizedBackendError(status: number, payload: unknown): Response {
  if (status === 409 && typeof payload === "object" && payload !== null) {
    const record = payload as Record<string, unknown>;
    if (typeof record.code === "string" && typeof record.message === "string") {
      return errorResponse(409, record.code, record.message);
    }
  }
  const messages: Record<number, [string, string]> = {
    404: ["not_found", "The requested local workflow was not found."],
    422: ["invalid_request", "Check the submitted fields and try again."],
    502: ["malformed_model_response", "The local model returned an invalid response."],
    503: ["local_service_unavailable", "The local backend or model is unavailable."],
    504: ["local_service_timeout", "The local backend or model timed out."],
  };
  const [code, message] = messages[status] ?? ["backend_error", "The local backend request failed."];
  return errorResponse(status, code, message);
}

export async function proxyToBackend(
  request: Request,
  backendPath: string,
): Promise<Response> {
  let backend: URL;
  try {
    backend = validateBackendUrl(process.env.BOUNDARY_BACKEND_URL ?? DEFAULT_BACKEND_URL);
  } catch {
    return errorResponse(503, "invalid_backend_configuration", "The local backend is not configured safely.");
  }

  let body: string | undefined;
  if (request.method === "POST") {
    body = await request.text();
    if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
      return errorResponse(413, "request_too_large", "The request is too large.");
    }
  }
  const target = new URL(backendPath, backend);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs());
  try {
    const response = await fetch(target, {
      method: request.method,
      body,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
      signal: controller.signal,
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return errorResponse(502, "malformed_backend_response", "The local backend returned unreadable data.");
    }
    if (!response.ok) {
      return sanitizedBackendError(response.status, payload);
    }
    return Response.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return errorResponse(504, "backend_timeout", "The local backend request timed out.");
    }
    return errorResponse(503, "backend_unavailable", "The local backend is unavailable.");
  } finally {
    clearTimeout(timer);
  }
}
