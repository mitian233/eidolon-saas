"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { MetadataList, MetadataListItem } from "@/components/app/admin/MetadataList";
import { StatusDot } from "@/components/app/StatusDot";
import { Timestamp } from "@/components/app/admin/Timestamp";
import { DashboardCard } from "@/components/admin/DashboardParts";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useWhileVisible } from "@/hooks/useWhileVisible";
import { copy } from "@/i18n";
import {
  BACKUP_BUSY_REFRESH_MS,
  type BackupHeadline,
  type BackupStatus,
  backUpNow,
  backupHeadline,
  bucketText,
  canBackUp,
  failureLines,
  formatBytes,
  getBackupStatus,
  settingsWillDo,
} from "@/lib/backups";
import { DASHBOARD_REFRESH_MS, formatFetchedAt } from "@/lib/dashboard";
import { FailureIcon } from "@/theme/icons";

const t = copy.admin.dashboard.backups;

/**
 * 看板上的「备份」：一句结论（正常、备份中、异常各种原因、未配置），上一次成功的时间和大小、存储桶里的份数和总量、
 * 保留期、空间提醒，最近一次失败的原因和来源；右上角「立即备份」。不随时间范围变，自己去问后端：页面看得见时
 * 每分钟一次，备份进行中时每 5 秒一次，结束后回到每分钟。`refreshKey` 变了（页首的「刷新」）马上再问一次。
 *
 * 点「立即备份」马上写「备份中…」并禁用按钮；已经有一次在进行（不管是谁发起的）时后端回冲突，同样写「备份中…」。
 */
export function BackupCard({ refreshKey }: { refreshKey: number }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** 点了「立即备份」、后端还没回话。 */
  const [pressed, setPressed] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  /** 只认最后发出的那次请求：先发的晚到，不能把刚开始的备份盖回「没在备份」。 */
  const latest = useRef(0);

  const load = useCallback(() => {
    const request = ++latest.current;
    getBackupStatus().then(
      (loaded) => {
        if (request !== latest.current) return;
        setStatus(loaded);
        setLoadError(null);
      },
      (e: Error) => {
        if (request === latest.current) setLoadError(e.message);
      },
    );
  }, []);

  useEffect(load, [load, refreshKey]);

  const headline = backupHeadline(status, pressed);
  useWhileVisible(load, headline?.kind === "busy" ? BACKUP_BUSY_REFRESH_MS : DASHBOARD_REFRESH_MS);

  async function backUp() {
    setPressed(true);
    setStartError(null);
    const request = ++latest.current;
    try {
      const began = await backUpNow();
      const now = began === "busy" ? await getBackupStatus() : began;
      if (request === latest.current) setStatus(now);
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setPressed(false);
    }
  }

  const busy = headline?.kind === "busy";
  const unavailable = headline?.kind === "unavailable";
  return (
    <DashboardCard
      title={t.title}
      hint={unavailable ? undefined : t.hint}
      level={2}
      action={!unavailable && (
        <Button
          variant="outline"
          size="sm"
          disabled={!canBackUp(status, pressed)}
          focusableWhenDisabled
          onClick={backUp}
          className="max-md:min-h-11"
        >
          {busy && <Spinner data-icon="inline-start" />}
          {busy ? t.backingUp : t.backUpNow}
        </Button>
      )}
    >
      <div className="flex flex-col gap-4">
        {startError !== null && (
          <Alert>
            <FailureIcon />
            <AlertTitle>{t.backUpFailed(startError)}</AlertTitle>
          </Alert>
        )}
        {loadError !== null && (
          <Alert>
            <FailureIcon />
            <AlertTitle>{t.loadFailed(loadError)}</AlertTitle>
          </Alert>
        )}
        {headline && <Headline headline={headline} status={status} />}
        {!unavailable && status && (status.configured || status.last !== null) && <Details status={status} />}
      </div>
    </DashboardCard>
  );
}

/** 一句结论：异常带红点并加粗，正常只写 muted 字；备份中带转圈，后面是谁发起、几点开始。未配置和配置有误时
 * 下面再跟一句怎么办或错在哪。 */
function Headline({ headline, status }: { headline: BackupHeadline; status: BackupStatus | null }) {
  if (headline.kind === "busy") {
    const underWay = status?.under_way;
    return (
      <p role="status" className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="inline-flex items-center gap-2 font-medium">
          <Spinner />
          {t.states.busy}
        </span>
        {underWay && (
          <span className="text-muted-foreground">
            {t.busySince(t.sources[underWay.source], formatFetchedAt(new Date(underWay.started_at)))}
          </span>
        )}
      </p>
    );
  }
  if (headline.kind === "ok") return <p className="text-sm text-muted-foreground">{t.states.ok}</p>;
  if (headline.kind === "unavailable") return <p className="text-sm text-muted-foreground">{headline.reason}</p>;
  const reason =
    headline.problem === "unconfigured" ? t.unconfiguredHelp : headline.problem === "misconfigured" ? status?.config_error : null;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="inline-flex items-center gap-2 font-medium">
        <StatusDot variant="error" />
        {t.states[headline.problem]}
      </p>
      {reason && <p className="break-words text-muted-foreground">{reason}</p>}
    </div>
  );
}

/** 上一次成功、存储桶里、保留期、空间提醒；最近一次没成功时，再加一项它错在哪。 */
function Details({ status }: { status: BackupStatus }) {
  const { last_success: success, bucket, last } = status;
  const failures = failureLines(last);
  /** 设置读不出来时，保留期和空间提醒都无从说起。 */
  const read = settingsWillDo(status);
  return (
    <MetadataList>
      <MetadataListItem label={t.lastSuccess}>
        {success ? (
          <>
            <Timestamp value={success.started_at} format="auto" />
            {`，${t.lastSuccessValue(formatBytes(success.size), t.sources[success.source])}`}
          </>
        ) : (
          t.never
        )}
      </MetadataListItem>
      <MetadataListItem label={t.bucket}>
        {bucket ? (
          <span className="flex flex-wrap items-center gap-x-3">
            <span className="tabular-nums">{bucketText(bucket)}</span>
            {bucket.over_warning && (
              <span className="inline-flex items-center gap-2 font-medium">
                <StatusDot variant="warning" />
                {t.overWarning}
              </span>
            )}
          </span>
        ) : (
          t.notListed
        )}
      </MetadataListItem>
      <MetadataListItem label={t.keepDays}>
        {read && status.keep_days !== null ? t.keepDaysValue(String(status.keep_days)) : "—"}
      </MetadataListItem>
      <MetadataListItem label={t.warnGb}>
        {!read ? "—" : status.warn_gb === null ? t.warnGbUnset : t.warnGbValue(String(status.warn_gb))}
      </MetadataListItem>
      {last && failures.length > 0 && (
        <MetadataListItem label={t.lastFailure}>
          <span className="flex flex-col gap-1">
            <span>
              <Timestamp value={last.started_at} format="auto" />
              {t.lastFailureAt(t.sources[last.source])}
            </span>
            {failures.map((line) => (
              <span key={line} className="text-muted-foreground">
                {line}
              </span>
            ))}
          </span>
        </MetadataListItem>
      )}
    </MetadataList>
  );
}
