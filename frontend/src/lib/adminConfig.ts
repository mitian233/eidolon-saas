// 后台只管理限额、玩法开关和注册方式；用户凭据由浏览器随请求携带。
import { api, json } from "@/lib/api";
import { EXEMPTING_SERVICES, type OwnService } from "@/lib/localOwnKeys";

export type ConfigStatus = "env" | "overridden" | "failed";
export type ItemName = "limits" | "affinity" | "reach_outs" | "letters" | "moments" | "schedule" | "cycles" | "bar" | "registration";
export type Shown = Record<string, string | number | boolean | null>;
export type ConfigItem = {
  status: ConfigStatus;
  env: Shown;
  effective: Shown;
  override: Shown | null;
  failure: string | null;
};
export type UnavailableItem = { unavailable: string };
export type AdminConfig = { [K in ItemName]: ConfigItem | UnavailableItem };

export function isAvailable(item: ConfigItem | UnavailableItem): item is ConfigItem {
  return !("unavailable" in item);
}

export const CONFIG_TABS = ["limits", "registration", "sponsor", "prices"] as const;
export type ConfigTab = (typeof CONFIG_TABS)[number];
export const TAB_ITEMS: Record<ConfigTab, ItemName[]> = {
  limits: ["limits", "affinity", "reach_outs", "letters", "moments", "schedule", "cycles", "bar"],
  registration: ["registration"],
  sponsor: [],
  prices: [],
};
export function isConfigTab(value: string): value is ConfigTab {
  return (CONFIG_TABS as readonly string[]).includes(value);
}
export function tabFromQuery(value: string | string[] | undefined): ConfigTab {
  return typeof value === "string" && isConfigTab(value) ? value : "limits";
}
export function tabHref(pathname: string, tab: ConfigTab): string {
  return tab === "limits" ? pathname : `${pathname}?tab=${tab}`;
}
export function tabHasFailure(config: AdminConfig, tab: ConfigTab): boolean {
  return TAB_ITEMS[tab].some((name) => {
    const item = config[name];
    return isAvailable(item) && statusDisplay(item).variant === "warning";
  });
}
export type StatusDisplay = {
  variant: "accent" | "warning" | null;
  canRestore: boolean;
  failure: string | null;
};
export function statusDisplay(item: ConfigItem): StatusDisplay {
  switch (item.status) {
    case "env": return { variant: null, canRestore: false, failure: null };
    case "overridden": return { variant: "accent", canRestore: true, failure: null };
    case "failed": return { variant: "warning", canRestore: true, failure: item.failure };
  }
}

export const REGISTRATIONS = ["open", "invite"] as const;
export const MAP_SITES = ["osm", "google", "amap"] as const;
export const LIMIT_FIELDS = [
  "turns_per_hour", "calls_per_hour", "photos_per_hour", "visits_per_hour", "read_alouds_per_hour",
  "call_minutes", "turns_per_call", "concurrent_calls", "history_turns",
] as const;
export const EXEMPTING_FIELDS = EXEMPTING_SERVICES.map((service) => `exempting_${service}`);
export function exemptingKeysOf(limits: Shown): OwnService[] {
  return EXEMPTING_SERVICES.filter((service) => limits[`exempting_${service}`] === true);
}
export type FieldKind = "select" | "limit" | "positive" | "switch";
export type FieldSpec = { name: string; kind: FieldKind; options?: readonly string[] };
export type ItemSpec = { rows: string[]; form: FieldSpec[] };
export const ITEM_SPECS: Record<ItemName, ItemSpec> = {
  limits: {
    rows: [...LIMIT_FIELDS, ...EXEMPTING_FIELDS],
    form: [
      ...LIMIT_FIELDS.map((name): FieldSpec => ({ name, kind: "limit" })),
      ...EXEMPTING_FIELDS.map((name): FieldSpec => ({ name, kind: "switch" })),
    ],
  },
  affinity: { rows: ["enabled"], form: [{ name: "enabled", kind: "switch" }] },
  reach_outs: {
    rows: ["enabled", "per_day"],
    form: [{ name: "enabled", kind: "switch" }, { name: "per_day", kind: "positive" }],
  },
  letters: { rows: ["enabled"], form: [{ name: "enabled", kind: "switch" }] },
  moments: {
    rows: ["enabled", "per_day", "map", "replies_per_day"],
    form: [
      { name: "enabled", kind: "switch" }, { name: "per_day", kind: "positive" },
      { name: "map", kind: "select", options: MAP_SITES }, { name: "replies_per_day", kind: "positive" },
    ],
  },
  schedule: { rows: ["enabled"], form: [{ name: "enabled", kind: "switch" }] },
  cycles: { rows: ["enabled"], form: [{ name: "enabled", kind: "switch" }] },
  bar: { rows: ["enabled"], form: [{ name: "enabled", kind: "switch" }] },
  registration: { rows: ["mode"], form: [{ name: "mode", kind: "select", options: REGISTRATIONS }] },
};
export type FieldRow = {
  field: string;
  env: Shown[string];
  effective: Shown[string];
  overridden: boolean;
  override: Shown[string];
  inEffect: boolean;
};
export function rows(item: ConfigItem, spec: ItemSpec): FieldRow[] {
  return spec.rows.map((field) => {
    const override = item.override?.[field];
    return {
      field, env: item.env[field] ?? null, effective: item.effective[field] ?? null,
      overridden: override !== undefined, override: override ?? null,
      inEffect: override !== undefined && item.status === "overridden",
    };
  });
}
export type Form = Record<string, string>;
export const UNLIMITED = "unlimited";
export function formOf(spec: ItemSpec, effective: Shown): Form {
  return Object.fromEntries(spec.form.map(({ name, kind }) => {
    const value = effective[name];
    if (kind === "limit" && !value) return [name, UNLIMITED];
    return [name, value === null || value === undefined ? "" : String(value)];
  }));
}
export function lockedOn(form: Form, field: string): boolean {
  return EXEMPTING_FIELDS.includes(field) && form[field] === "true"
    && EXEMPTING_FIELDS.filter((name) => form[name] === "true").length === 1;
}
export type Problem = { field: string; reason: "limit" | "positive" };
export type Change = Record<string, string | number | boolean>;
export function changeOf(spec: ItemSpec, form: Form): { change: Change } | { problems: Problem[] } {
  const change: Change = {};
  const problems: Problem[] = [];
  for (const { name, kind } of spec.form) {
    const typed = (form[name] ?? "").trim();
    switch (kind) {
      case "select": if (typed) change[name] = typed; break;
      case "switch": change[name] = form[name] === "true"; break;
      case "limit":
        if (typed === UNLIMITED) change[name] = 0;
        else if (!/^[1-9]\d*$/.test(typed)) problems.push({ field: name, reason: "limit" });
        else change[name] = Number(typed);
        break;
      case "positive":
        if (!/^[1-9]\d*$/.test(typed)) problems.push({ field: name, reason: "positive" });
        else change[name] = Number(typed);
        break;
    }
  }
  return problems.length ? { problems } : { change };
}
export async function getAdminConfig(): Promise<AdminConfig> {
  return json(await api("/api/admin/config"));
}
export async function saveItem(name: ItemName, change: Change): Promise<AdminConfig> {
  return json(await api(`/api/admin/config/${name}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(change),
  }));
}
export async function restoreItem(name: ItemName): Promise<AdminConfig> {
  return json(await api(`/api/admin/config/${name}`, { method: "DELETE" }));
}
