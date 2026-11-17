// Forwards /api/* to the backend at runtime, streaming both bodies: the request's, so that a
// data package being imported is never held whole in memory here, and the response's, so that
// server-sent events reach the browser as they arrive. The browser only ever talks to
// this origin: the session cookie, the Origin the backend checks, and the redirects of
// signing in with Google or GitHub all pass through here.

import { BACKEND_URL } from "@/lib/backend";

const NODE_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** Read the private node list at request time; an invalid entry invalidates the whole list. */
function callNodes(): Map<string, string> {
  const value: unknown = JSON.parse(process.env.EIDOLON_CALL_NODES ?? "");
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid call node configuration");
  const nodes = new Map<string, string>();
  for (const [id, address] of Object.entries(value)) {
    if (!NODE_ID.test(id) || typeof address !== "string" || !/^https?:\/\/[^/?#@\s]+\/?$/i.test(address)) {
      throw new Error("Invalid call node configuration");
    }
    const url = new URL(address);
    if (!url.hostname || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
      throw new Error("Invalid call node configuration");
    }
    nodes.set(id, url.origin);
  }
  return nodes;
}

async function forward(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const { search } = new URL(request.url);
  let url: string;
  const isCallNode = path[0] === "call-nodes";
  if (isCallNode) {
    if (path.length !== 3 || !NODE_ID.test(path[1]) || path[2] !== "offer" || !["POST", "PATCH"].includes(request.method)) {
      return new Response(null, { status: 404 });
    }
    let nodes: Map<string, string>;
    try {
      nodes = callNodes();
    } catch {
      return new Response("Call node configuration is invalid", { status: 503 });
    }
    const node = nodes.get(path[1]);
    if (!node) return new Response(null, { status: 404 });
    url = `${node}/api/offer${search}`;
  } else {
    url = `${BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${search}`;
  }
  const headers = new Headers();
  for (const name of ["content-type", "cookie", "origin", "x-timezone", "if-none-match"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    duplex: "half", // a stream as the body, sent while it is still being read
    cache: "no-store",
    redirect: "manual", // the browser follows the backend's redirects itself
  };
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (error) {
    if (!isCallNode) throw error;
    return new Response("Call node is unavailable", { status: 502 });
  }

  const out = new Headers();
  // the etag lets the browser revalidate an image instead of downloading it again; a data
  // package downloads under its name, with its size for the browser's progress
  for (const name of [
    "content-type",
    "x-content-type-options",
    "cache-control",
    "etag",
    "location",
    "retry-after",
    "content-disposition",
    "content-length",
  ]) {
    const value = res.headers.get(name);
    if (value) out.set(name, value);
  }
  // fetch hands on a compressed body decompressed, no longer the length the backend gave
  if (res.headers.has("content-encoding")) out.delete("content-length");
  for (const cookie of res.headers.getSetCookie()) out.append("set-cookie", cookie);
  // a 304 has no body, and Response refuses one for it
  return new Response(res.status === 304 ? null : res.body, { status: res.status, headers: out });
}

export const dynamic = "force-dynamic";
export { forward as GET, forward as HEAD, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };

export async function OPTIONS(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path[0] === "call-nodes") return new Response(null, { status: 404 });
  return new Response(null, { status: 204, headers: { Allow: "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE" } });
}
