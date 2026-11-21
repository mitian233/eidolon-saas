"use client";

import { useEffect, useState, type FormEvent } from "react";

import { AppLink } from "@/components/app/AppLink";
import { FailureNotice } from "@/components/app/FailureNotice";
import { AdminPage } from "@/components/app/admin/AdminPage";
import { Notice } from "@/components/app/admin/Notice";
import { Timestamp } from "@/components/app/admin/Timestamp";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { copy } from "@/i18n";
import { toFailure, type Failure } from "@/lib/failure";
import { listReports, REPORT_LIMITS, REPORTS_PAGE_SIZE, updateReport, type Report, type ReportPage, type ReportStatus } from "@/lib/reports";

const t = copy.admin.reports;
const statuses = (["open", "resolved", "dismissed"] as const).map((value) => ({ value, label: t.statuses[value] }));
const filters = [{ value: "all" as const, label: t.all }, ...statuses];

type Filter = ReportStatus | "all";

export function AdminReports() {
  const [status, setStatus] = useState<Filter>("open");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<ReportPage | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [saved, setSaved] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listReports(status, page, controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(data.total / REPORTS_PAGE_SIZE));
        if (page > lastPage) {
          setResult(null);
          setPage(lastPage);
        } else {
          setResult(data);
        }
      },
      (error) => { if (!controller.signal.aborted) setFailure(toFailure(error)); },
    );
    return () => controller.abort();
  }, [status, page, revision]);

  function changePage(nextPage: number) {
    setFailure(null);
    setResult(null);
    setPage(nextPage);
  }

  function savedReport() {
    setFailure(null);
    setSaved(true);
    setRevision((value) => value + 1);
  }

  const pages = result ? Math.ceil(result.total / REPORTS_PAGE_SIZE) : 0;
  return (
    <AdminPage width="narrow" title={copy.admin.pages.reports} intro={t.intro} end={
      <AppLink href="/admin/users">{t.users}</AppLink>
    }>
      <ToggleGroup aria-label={t.filter} value={[status]} className="flex-wrap" onValueChange={([value]) => {
        const nextStatus = filters.find((item) => item.value === value)?.value;
        if (nextStatus && nextStatus !== status) {
          setStatus(nextStatus);
          setSaved(false);
          changePage(1);
        }
      }}>
        {filters.map(({ value, label }) => <ToggleGroupItem key={value} value={value}>{label}</ToggleGroupItem>)}
      </ToggleGroup>
      {saved && <Notice text={t.saved} onDismiss={() => setSaved(false)} />}
      {failure && <FailureNotice failure={failure} />}
      {!result && !failure && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />{t.loading}</p>}
      {result?.total === 0 && <Empty><EmptyHeader><EmptyTitle>{t.empty}</EmptyTitle></EmptyHeader></Empty>}
      {result?.reports.map((report) => (
        <ReportCard key={`${report.id}:${report.updated_at}`} report={report} onSaved={savedReport} />
      ))}
      {pages > 1 && (
        <nav aria-label={t.pagination} className="flex flex-wrap items-center gap-3 text-sm tabular-nums">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => changePage(page - 1)}>{t.previous}</Button>
          <span>{t.page(page, pages)}</span>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => changePage(page + 1)}>{t.next}</Button>
        </nav>
      )}
    </AdminPage>
  );
}

function ReportCard({ report, onSaved }: { report: Report; onSaved: () => void }) {
  const [status, setStatus] = useState(report.status);
  const [note, setNote] = useState(report.note ?? "");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const statusId = `status-${report.id}`;
  const noteId = `note-${report.id}`;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setFailure(null);
    try {
      const updated = await updateReport(report.id, status, note);
      setNote(updated.note ?? "");
      onSaved();
    } catch (error) {
      setFailure(toFailure(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card role="article" aria-labelledby={`target-${report.id}`}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="min-w-0">
            <h2 id={`target-${report.id}`} className="wrap-anywhere">
              {report.target.length > 120 ? `${report.target.slice(0, 120)}…` : report.target}
            </h2>
          </CardTitle>
          <Badge variant={report.status === "resolved" ? "secondary" : "outline"}>{t.statuses[report.status]}</Badge>
        </div>
        <CardDescription className="flex flex-wrap gap-x-3 gap-y-1 wrap-anywhere">
          <span>{copy.report.categories[report.category]}</span>
          <span>{t.received} <Timestamp value={report.created_at} /></span>
          {report.processed_at && <span>{t.processed} <Timestamp value={report.processed_at} /></span>}
          <span>{t.number(report.id)}</span>
        </CardDescription>
      </CardHeader>
      <form onSubmit={save} className="flex flex-col gap-4">
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 text-sm wrap-anywhere">
            {report.target.length > 120 && (
              <details>
                <summary className="cursor-pointer">{t.fullTarget}</summary>
                <p className="mt-2 whitespace-pre-wrap">{report.target}</p>
              </details>
            )}
            <p className="whitespace-pre-wrap">{report.details}</p>
            {report.contact && <p>{t.contact} {report.contact}</p>}
          </div>
          {failure && <FailureNotice failure={failure} />}
          <FieldGroup>
            <Field data-disabled={pending}>
              <FieldLabel htmlFor={statusId}>{t.status}</FieldLabel>
              <Select value={status} items={statuses} disabled={pending} onValueChange={(value) => { if (value) setStatus(value); }}>
                <SelectTrigger id={statusId}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {statuses.map(({ value, label }) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field data-disabled={pending}>
              <FieldLabel htmlFor={noteId}>{t.note}</FieldLabel>
              <Textarea id={noteId} value={note} onChange={(event) => setNote(event.currentTarget.value)} maxLength={REPORT_LIMITS.note} disabled={pending} />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={pending || (status === report.status && note.trim() === (report.note ?? ""))}>
            {pending && <Spinner data-icon="inline-start" />}
            {t.save}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
