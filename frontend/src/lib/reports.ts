import { api, json } from "@/lib/api";

export type ReportCategory = "copyright" | "illegal" | "abuse" | "other";
export type ReportStatus = "open" | "resolved" | "dismissed";

export const REPORT_LIMITS = { target: 2048, details: 4000, contact: 320, note: 2000 } as const;
export const REPORTS_PAGE_SIZE = 25;

type ReportInput = { category: ReportCategory; target: string; details: string; contact: string };
export type Report = Omit<ReportInput, "contact"> & {
  id: string;
  contact: string | null;
  status: ReportStatus;
  note: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
};
export type ReportPage = { reports: Report[]; total: number };

export async function submitReport(input: ReportInput): Promise<{ id: string }> {
  return json(await api("/api/reports", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  }));
}

export async function listReports(status: ReportStatus | "all", page: number, signal: AbortSignal): Promise<ReportPage> {
  const params = new URLSearchParams({ offset: String((page - 1) * REPORTS_PAGE_SIZE), limit: String(REPORTS_PAGE_SIZE) });
  if (status !== "all") params.set("status", status);
  return json(await api(`/api/admin/reports?${params}`, { signal }));
}

export async function updateReport(id: string, status: ReportStatus, note: string): Promise<Report> {
  return json(await api(`/api/admin/reports/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status, note }),
  }));
}
