import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, OPTIONS, PATCH, POST } from "./route";

function backendAnswers(response: () => Response) {
  const fetch = vi.fn(async (_url: string, _init: RequestInit) => response());
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function get(path: string, headers: Record<string, string> = {}) {
  return GET(new Request(`http://localhost:3000/api/${path}`, { headers }), {
    params: Promise.resolve({ path: path.split("/") }),
  });
}

describe("forwarding /api/* to the backend", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("passes on what the browser needs to cache an image", async () => {
    backendAnswers(
      () =>
        new Response("jpeg", {
          headers: {
            "content-type": "image/jpeg",
            "x-content-type-options": "nosniff",
            "cache-control": "public, max-age=86400",
            etag: '"abc"',
          },
        }),
    );

    const res = await get("sponsor/image");

    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("cache-control")).toBe("public, max-age=86400");
    expect(res.headers.get("etag")).toBe('"abc"');
  });

  it("asks the backend whether the browser's copy is still current, and passes on its 304", async () => {
    const fetch = backendAnswers(() => new Response(null, { status: 304, headers: { etag: '"abc"' } }));

    const res = await get("sponsor/image", { "if-none-match": '"abc"' });

    const sent = new Headers(fetch.mock.calls[0][1].headers);
    expect(sent.get("if-none-match")).toBe('"abc"');
    expect(res.status).toBe(304);
    expect(res.body).toBeNull();
  });

  it("streams a request's body to the backend, and passes on a download's name and size", async () => {
    const fetch = backendAnswers(
      () =>
        new Response("zip", {
          headers: {
            "content-type": "application/zip",
            "content-disposition": 'attachment; filename="eidolon-data-package-2026-10-19.zip"',
            "content-length": "3",
          },
        }),
    );
    const body = new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]).stream();

    const res = await POST(
      new Request("http://localhost:3000/api/account/data-package?include=profile", {
        method: "POST",
        body,
        duplex: "half",
        headers: { "content-type": "application/zip" },
      } as RequestInit),
      { params: Promise.resolve({ path: ["account", "data-package"] }) },
    );

    const sent = fetch.mock.calls[0][1] as RequestInit & { duplex?: string };
    expect(sent.body).toBeInstanceOf(ReadableStream);
    expect(sent.duplex).toBe("half");
    expect(new Uint8Array(await new Response(sent.body).arrayBuffer())).toEqual(new Uint8Array([0x50, 0x4b, 0x03, 0x04]));
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="eidolon-data-package-2026-10-19.zip"');
    expect(res.headers.get("content-length")).toBe("3");
  });

  it("streams offers and candidates to the selected node with request and response headers", async () => {
    vi.stubEnv("EIDOLON_CALL_NODES", JSON.stringify({ node_1: "http://calls.internal:8001/", other: "https://other.internal" }));
    const fetch = backendAnswers(() => new Response("answer", { status: 201, headers: { "content-type": "application/json", "set-cookie": "session=next; HttpOnly" } }));
    for (const [method, handler] of [["POST", POST], ["PATCH", PATCH]] as const) {
      const request = new Request("http://localhost:3000/api/call-nodes/node_1/offer?pc=1", {
        method, body: `body-${method}`, headers: { cookie: "session=abc", origin: "https://example.test", "x-timezone": "Asia/Tokyo", "content-type": "application/json" },
      });
      const res = await handler(request, { params: Promise.resolve({ path: ["call-nodes", "node_1", "offer"] }) });
      const [url, init] = fetch.mock.calls[fetch.mock.calls.length - 1];
      expect(url).toBe("http://calls.internal:8001/api/offer?pc=1");
      expect(init.method).toBe(method);
      expect(init.body).toBe(request.body);
      expect(await new Response(init.body).text()).toBe(`body-${method}`);
      expect(Object.fromEntries(new Headers(init.headers))).toMatchObject({ cookie: "session=abc", origin: "https://example.test", "x-timezone": "Asia/Tokyo", "content-type": "application/json" });
      expect(res.status).toBe(201);
      expect(res.headers.get("set-cookie")).toContain("session=next");
      expect(await res.text()).toBe("answer");
    }
  });

  it("rejects unknown nodes, malformed selectors, other paths and methods without forwarding", async () => {
    vi.stubEnv("EIDOLON_CALL_NODES", JSON.stringify({ node_1: "http://calls.internal" }));
    const fetch = backendAnswers(() => new Response());
    const cases = [
      [POST, "POST", ["call-nodes", "missing", "offer"]],
      [POST, "POST", ["call-nodes", "__proto__", "offer"]],
      [POST, "POST", ["call-nodes", "", "offer"]],
      [POST, "POST", ["call-nodes", "../node_1", "offer"]],
      [POST, "POST", ["call-nodes", "node_1", "offer", "extra"]],
      [GET, "GET", ["call-nodes", "node_1", "offer"]],
      [OPTIONS, "OPTIONS", ["call-nodes", "node_1", "offer"]],
    ] as const;
    for (const [handler, method, path] of cases) {
      const res = await handler(new Request("http://localhost:3000/api/call-nodes", { method }), { params: Promise.resolve({ path: [...path] }) });
      expect(res.status, `${method} ${path.join("/")}`).toBe(404);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps direct offers on the backend even when node configuration is invalid", async () => {
    vi.stubEnv("EIDOLON_CALL_NODES", "bad config");
    const fetch = backendAnswers(() => new Response("answer"));
    const res = await POST(new Request("http://localhost:3000/api/offer", { method: "POST" }), { params: Promise.resolve({ path: ["offer"] }) });
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/offer$/);
    expect(await res.text()).toBe("answer");
  });

  it("rejects invalid node configuration without forwarding", async () => {
    const fetch = backendAnswers(() => new Response());
    for (const config of ["not json", "[]", '{"node_1":1}', '{"bad.id":"http://calls"}', '{"node_1":"http://user:secret@calls"}', '{"node_1":"http://calls/path"}', '{"node_1":"http://calls?x=1"}', '{"node_1":"http://calls#x"}', '{"node_1":"ftp://calls"}']) {
      vi.stubEnv("EIDOLON_CALL_NODES", config);
      const res = await POST(new Request("http://localhost:3000/api/call-nodes/node_1/offer", { method: "POST" }), { params: Promise.resolve({ path: ["call-nodes", "node_1", "offer"] }) });
      expect(res.status, config).toBe(503);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns a safe failure when the selected node is unreachable without retrying", async () => {
    vi.stubEnv("EIDOLON_CALL_NODES", JSON.stringify({ node_1: "http://calls.internal", other: "http://other.internal" }));
    const fetch = vi.fn(async () => { throw new Error("sensitive request details"); });
    vi.stubGlobal("fetch", fetch);
    const res = await POST(new Request("http://localhost:3000/api/call-nodes/node_1/offer", { method: "POST", body: "secret" }), { params: Promise.resolve({ path: ["call-nodes", "node_1", "offer"] }) });
    expect(res.status).toBe(502);
    expect(await res.text()).not.toContain("sensitive request details");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
