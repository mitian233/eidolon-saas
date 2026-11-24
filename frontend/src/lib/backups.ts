// The backups on the dashboard (GLOSSARY「备份」): how they stand, as the backend works it out,
// and the button that begins one. Nothing is judged here; the backend says what is wrong.

import { copy } from "@/i18n";
import { ApiError, api, json } from "@/lib/api";

/** Who began a backup run: the host's daily cron, the deployer by hand on the server, or an
 * admin with the button. */
export type BackupSource = "cron" | "manual" | "admin";

/** Where a run went wrong; `abandoned`, it never finished. */
export type BackupStage = "config" | "export" | "upload" | "prune" | "abandoned";

/** What is wrong with the backups: none of their settings set, some set wrong, none ever went
 * well, or the last that did is over 26 hours ago. */
export type BackupProblem = "unconfigured" | "misconfigured" | "never_succeeded" | "overdue";

/** A backup run not under way, however it went: `errors` empty when it went well. */
export type BackupRun = {
  source: BackupSource;
  started_at: string;
  errors: { stage: BackupStage; error: string | null }[];
};

export type BackupStatus = {
  /** Whether any of the settings a backup needs is set. */
  configured: boolean;
  /** Why they will not do; null when they do, or none is set. */
  config_error: string | null;
  /** Why this deployment uses external backups, when built-in backups are unavailable. */
  unavailable_reason?: string;
  /** The settings, as they are now; null when they will not do. */
  keep_days: number | null;
  warn_gb: number | null;
  /** The run under way, whoever began it. */
  under_way: { source: BackupSource; started_at: string } | null;
  last_success: {
    source: BackupSource;
    started_at: string;
    /** Bytes, compressed and encrypted. */
    size: number;
  } | null;
  /** The latest run not under way, which may have gone wrong. */
  last: BackupRun | null;
  /** What is in the bucket, as the latest run that listed it saw; `total` is null where the
   * bucket did not say each one's size. */
  bucket: { kept: number; total: number | null; over_warning: boolean } | null;
  problem: BackupProblem | null;
};

export async function getBackupStatus(): Promise<BackupStatus> {
  return json(await api("/api/admin/backups"));
}

/** Begin a backup in the server: how the backups stand with it under way, or "busy" when one
 * already was. Any other failure throws, with the backend's reason. */
export async function backUpNow(): Promise<BackupStatus | "busy"> {
  try {
    return await json(await api("/api/admin/backups", { method: "POST" }));
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return "busy";
    throw e;
  }
}

/** How often the dashboard asks how the backups stand while one is under way, to show its
 * result soon after it is done; otherwise it asks once a minute, as for the rest. */
export const BACKUP_BUSY_REFRESH_MS = 5_000;

/** What the block says first: a backup under way (begun now from the button, or seen under
 * way, by whoever), else what is wrong, else that all is well. */
export type BackupHeadline =
  | { kind: "busy" }
  | { kind: "ok" }
  | { kind: "problem"; problem: BackupProblem }
  | { kind: "unavailable"; reason: string };

export function backupHeadline(status: BackupStatus | null, pressed: boolean): BackupHeadline | null {
  if (status?.unavailable_reason) return { kind: "unavailable", reason: status.unavailable_reason };
  if (pressed || status?.under_way) return { kind: "busy" };
  if (status === null) return null;
  return status.problem === null ? { kind: "ok" } : { kind: "problem", problem: status.problem };
}

/** Whether the settings are set and will do: the backend read them, and would begin a backup. */
export function settingsWillDo(status: BackupStatus): boolean {
  return !status.unavailable_reason && status.problem !== "unconfigured" && status.problem !== "misconfigured";
}

/** Whether the button may begin a backup: not while one is under way, nor without settings
 * that will do, which the backend would refuse. */
export function canBackUp(status: BackupStatus | null, pressed: boolean): boolean {
  if (status === null || backupHeadline(status, pressed)?.kind === "busy") return false;
  return settingsWillDo(status);
}

/** What a finished run that went wrong did wrong, a line for each: 「上传失败：…」. None for a
 * run that went well. */
export function failureLines(run: BackupRun | null): string[] {
  const stages = copy.admin.dashboard.backups.stages;
  return (run?.errors ?? []).map(({ stage, error }) => (error ? `${stages[stage]}：${error}` : stages[stage]));
}

/** What is in the bucket: 「12 份，共 924.1 MB」. */
export function bucketText(bucket: NonNullable<BackupStatus["bucket"]>): string {
  const words = copy.admin.dashboard.backups;
  const kept = String(bucket.kept);
  return bucket.total === null ? words.bucketNoSize(kept) : words.bucketValue(kept, formatBytes(bucket.total));
}

/** Bytes as storage bills them, in powers of a thousand: 「77.3 MB」「2.31 GB」. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} 字节`;
}
