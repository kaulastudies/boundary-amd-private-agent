export type Health = {
  status: "ok";
  service: string;
  model: string;
  remote_apis_enabled: false;
};

export const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8080";

export function healthLabel(health: Health | null): string {
  return health?.status === "ok" ? "Backend online" : "Backend unavailable";
}

export async function fetchHealth(): Promise<Health | null> {
  try {
    const response = await fetch(`${backendUrl}/health`, { cache: "no-store" });
    return response.ok ? (await response.json()) as Health : null;
  } catch {
    return null;
  }
}
