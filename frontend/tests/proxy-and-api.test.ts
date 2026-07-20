// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { boundaryApi } from "@/lib/api";
import { proxyToBackend, validateBackendUrl } from "@/lib/server/backend-proxy";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.BOUNDARY_BACKEND_URL;
});

describe("local proxy boundary", () => {
  it("accepts loopback/private origins and rejects public or unsupported origins", () => {
    expect(validateBackendUrl("http://127.0.0.1:8080").hostname).toBe("127.0.0.1");
    expect(validateBackendUrl("http://192.168.1.20:8080").hostname).toBe("192.168.1.20");
    expect(() => validateBackendUrl("https://example.com")).toThrow(/local or private/);
    expect(() => validateBackendUrl("ftp://127.0.0.1:8080")).toThrow(/scheme/);
  });

  it("browser API calls only same-origin proxy paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok", service: "backend", model: "boundary-qwen3-8b", remote_apis_enabled: false,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await boundaryApi.health();
    expect(fetchMock).toHaveBeenCalledWith("/api/boundary/health", expect.any(Object));
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("127.0.0.1:8080");
  });

  it("refuses unsafe server configuration before any backend request", async () => {
    process.env.BOUNDARY_BACKEND_URL = "https://public.example.com";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const response = await proxyToBackend(new Request("http://localhost/api", { method: "GET" }), "/health");
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      code: "invalid_backend_configuration",
      message: "The local backend is not configured safely.",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
