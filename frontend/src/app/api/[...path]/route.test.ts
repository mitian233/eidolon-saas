import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "./route";

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
  });

  it("passes on what the browser needs to cache an image", async () => {
    backendAnswers(
      () =>
        new Response("jpeg", {
          headers: {
            "content-type": "image/jpeg",
            "cache-control": "public, max-age=86400",
            etag: '"abc"',
          },
        }),
    );

    const res = await get("sponsor/image");

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
});
