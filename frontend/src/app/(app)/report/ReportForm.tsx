"use client";

import { useState, type FormEvent } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/i18n";
import { ApiError } from "@/lib/api";
import { REPORT_LIMITS, submitReport, type ReportCategory } from "@/lib/reports";

const t = copy.report;
const categories = (["copyright", "illegal", "abuse", "other"] as const).map((value) => ({ value, label: t.categories[value] }));

export function ReportForm() {
  const [category, setCategory] = useState<ReportCategory | null>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    const target = String(fields.get("target") ?? "").trim();
    const details = String(fields.get("details") ?? "").trim();
    const contact = String(fields.get("contact") ?? "").trim();
    if (!category || !target || !details) {
      setFailure(t.invalid);
      return;
    }
    setFailure(null);
    setPending(true);
    try {
      const { id } = await submitReport({ category, target, details, contact });
      setReceipt(id);
      setCategory(null);
    } catch (error) {
      setFailure(error instanceof ApiError && error.status === 429 ? error.message : t.failed);
    } finally {
      setPending(false);
    }
  }

  if (receipt) {
    return (
      <div className="flex flex-col items-start gap-4">
        <Alert role="status">
          <AlertTitle>{t.received}</AlertTitle>
          <AlertDescription>{t.receipt(receipt)}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => setReceipt(null)}>{t.newReport}</Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col items-start gap-4">
      <FieldGroup>
        <Field data-disabled={pending}>
          <FieldLabel htmlFor="report-category">{t.category}</FieldLabel>
          <Select name="category" items={categories} value={category} onValueChange={setCategory} required disabled={pending}>
            <SelectTrigger id="report-category" className="w-full">
              <SelectValue placeholder={t.chooseCategory} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {categories.map(({ value, label }) => <SelectItem key={value} value={value}>{label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field data-disabled={pending}>
          <FieldLabel htmlFor="report-target">{t.target}</FieldLabel>
          <Input id="report-target" name="target" maxLength={REPORT_LIMITS.target} aria-describedby="report-target-hint" required disabled={pending} />
          <FieldDescription id="report-target-hint">{t.targetHint}</FieldDescription>
        </Field>
        <Field data-disabled={pending}>
          <FieldLabel htmlFor="report-details">{t.details}</FieldLabel>
          <Textarea id="report-details" name="details" rows={5} maxLength={REPORT_LIMITS.details} aria-describedby="report-details-hint" required disabled={pending} />
          <FieldDescription id="report-details-hint">{t.detailsHint}</FieldDescription>
        </Field>
        <Field data-disabled={pending}>
          <FieldLabel htmlFor="report-contact">{t.contact}</FieldLabel>
          <Input id="report-contact" name="contact" maxLength={REPORT_LIMITS.contact} aria-describedby="report-contact-hint" disabled={pending} />
          <FieldDescription id="report-contact-hint">{t.contactHint}</FieldDescription>
        </Field>
      </FieldGroup>
      {failure && <Alert role="alert" variant="destructive"><AlertTitle>{failure}</AlertTitle></Alert>}
      <Button type="submit" size="lg" disabled={pending}>
        {pending && <Spinner data-icon="inline-start" />}
        {pending ? t.submitting : t.submit}
      </Button>
    </form>
  );
}
