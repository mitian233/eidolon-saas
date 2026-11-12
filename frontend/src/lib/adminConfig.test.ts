import { afterEach, describe, expect, it, vi } from "vitest";

import {
  changeOf,
  CONFIG_TABS,
  formOf,
  exemptingKeysOf,
  ITEM_SPECS,
  lockedOn,
  UNLIMITED,
  statusDisplay,
  saveItem,
  TAB_ITEMS,
  tabFromQuery,
  tabHasFailure,
  tabHref,
  type AdminConfig,
  type ConfigItem,
  type Shown,
} from "@/lib/adminConfig";

const ENV: Shown = { enabled: false };
const OVERRIDE: Shown = { enabled: true };

afterEach(() => vi.unstubAllGlobals());

describe("saveItem", () => {
  it("sends configuration changes as JSON", async () => {
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => Response.json({}));
    vi.stubGlobal("fetch", fetch);

    await saveItem("affinity", { enabled: true });

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/admin/config/affinity");
    expect(init?.method).toBe("PUT");
    expect(new Headers(init?.headers).get("content-type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ enabled: true });
  });
});

function item(status: ConfigItem["status"]): ConfigItem {
  return {
    status,
    env: ENV,
    effective: status === "overridden" ? { ...ENV, ...OVERRIDE } : ENV,
    override: status === "env" ? null : OVERRIDE,
    failure: status === "failed" ? "401 key revoked" : null,
  };
}

describe("statusDisplay", () => {
  it("marks only the overridden and failed states, restorable once overridden, with why it is not in effect", () => {
    expect(statusDisplay(item("env"))).toEqual({ variant: null, canRestore: false, failure: null });
    expect(statusDisplay(item("overridden"))).toEqual({ variant: "accent", canRestore: true, failure: null });
    expect(statusDisplay(item("failed"))).toEqual({
      variant: "warning",
      canRestore: true,
      failure: "401 key revoked",
    });
  });
});


describe("limits", () => {
  const limits = ITEM_SPECS.limits;
  const form = {
    turns_per_hour: "2",
    calls_per_hour: UNLIMITED,
    photos_per_hour: "5",
    visits_per_hour: "3",
    read_alouds_per_hour: "60",
    call_minutes: "10",
    turns_per_call: "40",
    concurrent_calls: "10",
    history_turns: "20",
    exempting_llm: "true",
    exempting_tts: "false",
    exempting_stt: "true",
  };

  it("starts a limit of 0 as none, not as a number", () => {
    expect(formOf(limits, { ...form, calls_per_hour: 0, turns_per_hour: 2 }).calls_per_hour).toBe(UNLIMITED);
    expect(formOf(limits, { ...form, calls_per_hour: 0, turns_per_hour: 2 }).turns_per_hour).toBe("2");
  });

  it("takes whole numbers from 1 up, and sends none as 0", () => {
    expect(changeOf(limits, form)).toEqual({
      change: {
        turns_per_hour: 2,
        calls_per_hour: 0,
        photos_per_hour: 5,
        visits_per_hour: 3,
        read_alouds_per_hour: 60,
        call_minutes: 10,
        turns_per_call: 40,
        concurrent_calls: 10,
        history_turns: 20,
        exempting_llm: true,
        exempting_tts: false,
        exempting_stt: true,
      },
    });
  });

  it("never has image generation among the exempting keys, though users may bring their own", () => {
    expect(exemptingKeysOf({ exempting_llm: true, exempting_tts: true, exempting_stt: true, exempting_image: true })).toEqual([
      "llm",
      "tts",
      "stt",
    ]);
  });

  it("reads which services are the exempting keys from the effective limits", () => {
    expect(exemptingKeysOf({ turns_per_hour: 60, exempting_llm: true, exempting_tts: false, exempting_stt: true })).toEqual([
      "llm",
      "stt",
    ]);
    expect(exemptingKeysOf({ exempting_llm: false, exempting_tts: true, exempting_stt: false })).toEqual(["tts"]);
  });

  it("keeps the last exempting key on from being turned off, and no other switch", () => {
    const llmAlone = { ...form, exempting_stt: "false" };
    expect(lockedOn(llmAlone, "exempting_llm")).toBe(true);
    expect(lockedOn(llmAlone, "exempting_tts")).toBe(false); // off: it can be turned on
    expect(lockedOn(form, "exempting_llm")).toBe(false); // another is on
    expect(lockedOn({ ...llmAlone, enabled: "true" }, "enabled")).toBe(false);
  });

  it("refuses one that is 0, negative, not whole or empty", () => {
    for (const bad of ["0", "-1", "1.5", "", "十"]) {
      expect(changeOf(limits, { ...form, calls_per_hour: bad }), bad).toEqual({
        problems: [{ field: "calls_per_hour", reason: "limit" }],
      });
    }
  });
});

describe("reach-outs", () => {
  const spec = ITEM_SPECS.reach_outs;

  it("send the switch and how many a day, a whole number from 1 up", () => {
    const form = formOf(spec, { enabled: false, per_day: 3 });
    expect(form).toEqual({ enabled: "false", per_day: "3" });
    expect(changeOf(spec, { enabled: "true", per_day: " 12 " })).toEqual({
      change: { enabled: true, per_day: 12 },
    });
    for (const bad of ["0", "", "1.5", "-2"]) {
      expect(changeOf(spec, { ...form, per_day: bad }), bad).toEqual({
        problems: [{ field: "per_day", reason: "positive" }],
      });
    }
  });
});

describe("moments", () => {
  const spec = ITEM_SPECS.moments;

  it("send the switch, how many a day, which map and how many comments a day she replies to", () => {
    const form = formOf(spec, { enabled: true, per_day: 3, map: "osm", replies_per_day: 10 });
    expect(form).toEqual({ enabled: "true", per_day: "3", map: "osm", replies_per_day: "10" });
    expect(changeOf(spec, { ...form, map: "amap", replies_per_day: "5" })).toEqual({
      change: { enabled: true, per_day: 3, map: "amap", replies_per_day: 5 },
    });
  });
});

describe("schedule", () => {
  const spec = ITEM_SPECS.schedule;

  it("send only the switch", () => {
    expect(formOf(spec, { enabled: true })).toEqual({ enabled: "true" });
    expect(changeOf(spec, { enabled: "false" })).toEqual({ change: { enabled: false } });
  });
});

describe("cycles and the bar", () => {
  it("are cards of limits and play: letters and moments after reach-outs, cycles and the bar after the schedule", () => {
    expect(TAB_ITEMS.limits).toEqual([
      "limits",
      "affinity",
      "reach_outs",
      "letters",
      "moments",
      "schedule",
      "cycles",
      "bar",
    ]);
  });
});

describe("tabs", () => {
  it("put every item under exactly one tab", () => {
    const placed = CONFIG_TABS.flatMap((tab) => TAB_ITEMS[tab]);
    expect([...placed].sort()).toEqual(Object.keys(ITEM_SPECS).sort());
  });

  it("takes operational tabs from the address and defaults to limits", () => {
    expect(tabFromQuery("registration")).toBe("registration");
    expect(tabFromQuery("prices")).toBe("prices");
    for (const value of [undefined, "nope", "voice", "network", "models"]) expect(tabFromQuery(value), String(value)).toBe("limits");
  });

  it("leave the default tab out of the address", () => {
    expect(tabHref("/admin/config", "limits")).toBe("/admin/config");
    expect(tabHref("/admin/config", "registration")).toBe("/admin/config?tab=registration");
  });

  it("mark a tab holding an override not in effect, not one holding an unavailable item", () => {
    const config = {
      ...Object.fromEntries(Object.keys(ITEM_SPECS).map((name) => [name, item("env")])),
      affinity: item("failed"),
    } as unknown as AdminConfig;
    expect(CONFIG_TABS.filter((tab) => tabHasFailure(config, tab))).toEqual(["limits"]);
  });
});
