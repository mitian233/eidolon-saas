import { describe, expect, it } from "vitest";

import { type BackupStatus, backupHeadline, bucketText, canBackUp, failureLines, formatBytes } from "@/lib/backups";

const WELL: BackupStatus = {
  configured: true,
  config_error: null,
  keep_days: 30,
  warn_gb: null,
  under_way: null,
  last_success: { source: "cron", started_at: "2026-10-15T03:00:00+00:00", size: 77_300_000 },
  last: { source: "cron", started_at: "2026-10-15T03:00:00+00:00", errors: [] },
  bucket: { kept: 12, total: 924_100_000, over_warning: false },
  problem: null,
};

const UNDER_WAY = { source: "cron", started_at: "2026-10-16T03:00:00+00:00" } as const;

describe("backupHeadline", () => {
  it("says a backup is under way whoever began it, before anything wrong", () => {
    expect(backupHeadline({ ...WELL, under_way: UNDER_WAY, problem: "overdue" }, false)).toEqual({ kind: "busy" });
  });

  it("says a backup is under way as soon as the button is pressed, before the backend says so", () => {
    expect(backupHeadline(null, true)).toEqual({ kind: "busy" });
  });

  it("says what the backend found wrong, else that all is well", () => {
    expect(backupHeadline({ ...WELL, problem: "unconfigured" }, false)).toEqual({
      kind: "problem",
      problem: "unconfigured",
    });
    expect(backupHeadline(WELL, false)).toEqual({ kind: "ok" });
    expect(backupHeadline(null, false)).toBeNull();
  });

  it("shows the reason when built-in backups are unavailable and disallows starting one", () => {
    const reason = "内置备份与恢复仅适用于 SQLite；PostgreSQL 请使用 pg_dump 与 age 加密备份";
    const status = { ...WELL, configured: false, unavailable_reason: reason };
    expect(backupHeadline(status, false)).toEqual({ kind: "unavailable", reason });
    expect(canBackUp(status, false)).toBe(false);
  });
});

describe("canBackUp", () => {
  it("lets a backup begin unless one is under way or the settings will not do", () => {
    expect(canBackUp({ ...WELL, problem: "overdue" }, false)).toBe(true);
    expect(canBackUp({ ...WELL, under_way: UNDER_WAY }, false)).toBe(false);
    expect(canBackUp({ ...WELL, problem: "unconfigured" }, false)).toBe(false);
    expect(canBackUp({ ...WELL, problem: "misconfigured" }, false)).toBe(false);
    expect(canBackUp(null, false)).toBe(false);
  });
});

describe("failureLines", () => {
  it("names each stage that went wrong with its reason, and an abandoned run without one", () => {
    expect(
      failureLines({
        ...WELL.last!,
        errors: [
          { stage: "upload", error: "存储桶返回了 503" },
          { stage: "prune", error: "存储桶返回了 503" },
        ],
      }),
    ).toEqual(["上传失败：存储桶返回了 503", "清理过期备份失败：存储桶返回了 503"]);
    expect(failureLines({ ...WELL.last!, errors: [{ stage: "abandoned", error: null }] })).toEqual([
      "没有完成（进程中途退出，或服务重启）",
    ]);
    expect(failureLines(WELL.last)).toEqual([]);
    expect(failureLines(null)).toEqual([]);
  });
});

describe("bucketText", () => {
  it("counts the backups and their size, or says the bucket gave none", () => {
    expect(bucketText(WELL.bucket!)).toBe("12 份，共 924.1 MB");
    expect(bucketText({ ...WELL.bucket!, total: null })).toBe("12 份（存储桶没有给出大小）");
  });
});

describe("formatBytes", () => {
  it("writes bytes in powers of a thousand, as storage bills them", () => {
    expect(formatBytes(2_310_000_000)).toBe("2.31 GB");
    expect(formatBytes(77_300_000)).toBe("77.3 MB");
    expect(formatBytes(4_500)).toBe("4.5 KB");
    expect(formatBytes(300)).toBe("300 字节");
  });
});
