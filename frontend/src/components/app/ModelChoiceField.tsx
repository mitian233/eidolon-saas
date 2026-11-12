"use client";

import { useState } from "react";

import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const CUSTOM_MODEL = "__custom__";
const modelChoice = (models: string[], value: string) => models.includes(value) ? value : CUSTOM_MODEL;

/**
 * 模型：下拉里是常用的几个，最后一项「其他（手填）」。选了它，下拉下面出一个框填模型名；表单里存的始终是模型名本身，
 * 不在下拉里的名字打开时就落在「其他（手填）」上。
 */
export function ModelChoiceField({
  id,
  label,
  options,
  customLabel,
  value,
  onChange,
  error,
}: {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  customLabel: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
}) {
  const items = [...options, { value: CUSTOM_MODEL, label: customLabel }];
  const listed = options.map((o) => o.value);
  // 选了「其他（手填）」就一直停在上面，手填时半路打出下拉里有的名字也不跳走
  const [typing, setTyping] = useState(() => modelChoice(listed, value) === CUSTOM_MODEL);
  const choice = typing ? CUSTOM_MODEL : modelChoice(listed, value);
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select
        items={items}
        value={choice}
        onValueChange={(next) => {
          if (!next || next === choice) return;
          setTyping(next === CUSTOM_MODEL);
          onChange(next === CUSTOM_MODEL ? "" : String(next));
        }}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {choice === CUSTOM_MODEL && (
        <Input
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={error ? true : undefined}
          autoComplete="off"
        />
      )}
      {error && <FieldError>{error}</FieldError>}
    </Field>
  );
}
