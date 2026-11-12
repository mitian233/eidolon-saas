"use client";

import { useId } from "react";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";

export function OwnJudgeSetting({ enabled, disabled, onChange }: {
  enabled: boolean;
  disabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const id = useId();
  const t = copy.settings.ownKeys;
  return (
    <Field>
      <div className="flex items-center justify-between gap-3">
        <FieldLabel htmlFor={id}>{t.judgeTitle}</FieldLabel>
        <Switch id={id} checked={enabled} disabled={disabled} onCheckedChange={onChange} aria-describedby={`${id}-note`} />
      </div>
      <FieldDescription id={`${id}-note`}>{enabled ? t.judgeOn : t.judgeOff}</FieldDescription>
    </Field>
  );
}
