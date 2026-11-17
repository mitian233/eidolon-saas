// startCall 的 seam：Pipecat 的 client 和 WebRTC transport、麦克风都换成假的，不跑真的 WebRTC。
// 只测一件事：offer 带上这个浏览器为这位用户存的自带密钥，接通以后之后每次重新协商都不再带。
// 通话的其他行为由 liveConversation.test.ts 经假的通话覆盖。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startCall } from "@/lib/call";
import type { CallPreferences } from "@/lib/callPreferences";
import { keepOwnKey } from "@/lib/localOwnKeys";

/** 假的 Pipecat client 每次 `connect` 收到的 offer 参数。Pipecat 按引用持有其中的请求数据，
 * 之后每次重新协商都把同一份再发一遍；这里留着同一个引用，好看接通后它变成了什么。 */
const offers = vi.hoisted(() => [] as { endpoint: string; requestData: Record<string, unknown>; sentWithOffer: unknown }[]);

vi.mock("@pipecat-ai/client-js", () => ({
  TransportStartError: class extends Error {},
  PipecatClient: class {
    async connect({ webrtcRequestParams }: { webrtcRequestParams: { endpoint: string; requestData: Record<string, unknown> } }) {
      const { endpoint, requestData } = webrtcRequestParams;
      // offer 发出去的那一刻请求数据是什么样（发出去的是它的 JSON）。
      offers.push({ endpoint, requestData, sentWithOffer: JSON.parse(JSON.stringify(requestData)) });
    }
    async disconnect() {}
    sendClientMessage() {}
  },
}));

vi.mock("@pipecat-ai/small-webrtc-transport", () => ({ SmallWebRTCTransport: class {} }));

vi.mock("@/lib/microphone", () => ({
  Microphone: {
    open: async () => ({ inUse: { id: "", fellBack: false }, disconnect: async () => {}, enableMic() {} }),
  },
}));

const LLM = {
  api_key: "sk-my-own-key-1234",
  base_url: "https://llm.example.com/v1",
  model: "my-model",
  protocol: "chat-completions",
} as const;
const TTS = { api_key: "fish-my-own-key" };
const STT = { api_key: "soniox-my-own-key", provider: "soniox" } as const;

const PREFERENCES: CallPreferences = { micId: "", quality: "standard", muted: false, phoneTexture: false };
const HANDLERS = {
  onMicOpen() {},
  onEvent() {},
  onHearing() {},
  onCharacterAudio() {},
  onDropped() {},
  onMicLost() {},
};

beforeEach(() => {
  offers.length = 0;
  const items = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  });
  // 拨号前的预检。
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ iceServers: [], maxCallSeconds: null, callExempt: true })),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("startCall", () => {
  it("brings the user's own keys with the offer, and no longer once the call has connected", async () => {
    keepOwnKey("u1", "llm", LLM);
    keepOwnKey("u1", "tts", TTS);
    keepOwnKey("u1", "stt", STT);

    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      iceServers: [], maxCallSeconds: null, callExempt: true, offerEndpoint: "/api/call-nodes/node_1/offer",
    })));
    await startCall("c1", PREFERENCES, HANDLERS, "u1");

    expect(offers).toHaveLength(1);
    const [{ requestData, sentWithOffer }] = offers;
    expect(offers[0].endpoint).toBe("/api/call-nodes/node_1/offer");
    expect(sentWithOffer).toMatchObject({ conversation_id: "c1", own_keys: { llm: LLM, tts: TTS, stt: STT } });
    // 之后每次重新协商发的都是这同一份请求数据。
    expect(requestData).not.toHaveProperty("own_keys");
    expect(requestData).toMatchObject({ conversation_id: "c1" });
  });

  it("uses the direct offer endpoint when setup has no selected node", async () => {
    await startCall("c1", PREFERENCES, HANDLERS, "u1");
    expect(offers[0].endpoint).toBe("/api/offer");
  });
});
