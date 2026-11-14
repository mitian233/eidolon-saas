"use client";

import { useId, useState, type FormEvent } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/i18n";
import type { Character, CharacterInput } from "@/lib/api";
import {
  CHARACTER_LIMITS,
  DEFAULT_USER_ADDRESS,
  draftProblems,
  fromDraft,
  sameDraft,
  toDraft,
  type CharacterDraft,
  type DraftProblem,
} from "@/lib/characterDraft";
import { toFailure, type Failure } from "@/lib/failure";
import { chooseBirthMonth, daysInMonth } from "@/lib/producerProfile";

const t = copy.characterForm;

/** 「不填」在选择框里用这个值代表（选择框的值不用空字符串），草稿里是 null。 */
const UNSET = "unset";

const PROBLEM_MESSAGES: Record<DraftProblem, string> = {
  name: t.nameMissing,
  sheet: t.sheetMissing,
  avatarUrl: t.avatarUrlInvalid,
  color: t.colorInvalid,
  age: t.ageInvalid,
  birthDay: t.birthDayMissing,
};

type Props = {
  /** 表单从哪份草稿开始：新建是空草稿，编辑是她现在的样子。 */
  initial: CharacterDraft;
  /** `new`：提交键写「创建」，填好就能交；`edit`：写「保存」，有改动才能交，旁边一句存没存。 */
  mode: "new" | "edit";
  /** 交给后端，返回存下的她；失败时抛出的原因显示在表单底下。 */
  onSave: (input: CharacterInput) => Promise<Character>;
  onCancel: () => void;
};

/**
 * 新建、编辑角色的表单：名字、简介、人设、头像地址、问候语、音色 ID、主题色、她怎么称呼你、回复语言、生日、年龄。
 * 点过提交、被挡下之后才在有问题的项下面提示（lib/characterDraft 的 draftProblems），之后边改边更新。
 * 判断模型开关不在这里，在设置的自带密钥里（账户级）。
 */
export function CharacterForm({ initial, mode, onSave, onCancel }: Props) {
  const id = useId();
  const [draft, setDraft] = useState(initial);
  // 编辑时存好一次，「有没有改动」就以存下的为准。
  const [saved, setSaved] = useState(initial);
  const [triedToSave, setTriedToSave] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  const problems = triedToSave ? new Set(draftProblems(draft)) : new Set<DraftProblem>();
  const dirty = !sameDraft(draft, saved);
  const update = (change: Partial<CharacterDraft>) => setDraft((current) => ({ ...current, ...change }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (draftProblems(draft).length > 0) {
      setTriedToSave(true);
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      const character = await onSave(fromDraft(draft));
      const stored = toDraft(character);
      setDraft(stored);
      setSaved(stored);
      setTriedToSave(false);
    } catch (e) {
      setFailure(toFailure(e));
    } finally {
      setSaving(false);
    }
  }

  /** 一项的错误提示；这一项没问题时什么都没有。 */
  const invalid = (problem: DraftProblem) =>
    problems.has(problem)
      ? { "aria-invalid": true as const, "aria-describedby": `${id}-${problem}-error` }
      : { "aria-invalid": undefined };
  const error = (problem: DraftProblem) =>
    problems.has(problem) && <FieldError id={`${id}-${problem}-error`}>{PROBLEM_MESSAGES[problem]}</FieldError>;

  const monthOptions = [
    { value: UNSET, label: t.birthdayUnset },
    ...range(12).map((month) => ({ value: String(month), label: t.monthOption(String(month)) })),
  ];
  const dayOptions = [
    { value: UNSET, label: t.birthdayUnset },
    ...(draft.birthMonth === null ? [] : range(daysInMonth(draft.birthMonth))).map((day) => ({
      value: String(day),
      label: t.dayOption(String(day)),
    })),
  ];
  const languageOptions = (Object.keys(t.languageModes) as CharacterDraft["languageMode"][]).map((value) => ({
    value,
    label: t.languageModes[value],
  }));

  return (
    <form onSubmit={submit} noValidate>
      {/* 保存中整张表单锁住：等待时的改动会被存下的结果盖掉，取消也拦不住已经发出去的请求。 */}
      <fieldset disabled={saving} className="contents">
        <FieldGroup>
          <Field data-invalid={problems.has("name") || undefined}>
            <FieldLabel htmlFor={`${id}-name`}>{t.name}</FieldLabel>
            <Input
              id={`${id}-name`}
              value={draft.name}
              onChange={(event) => update({ name: event.target.value })}
              maxLength={CHARACTER_LIMITS.name}
              autoComplete="off"
              required
              {...invalid("name")}
            />
            {error("name")}
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-intro`}>{t.intro}</FieldLabel>
            <Textarea
              id={`${id}-intro`}
              value={draft.intro}
              onChange={(event) => update({ intro: event.target.value })}
              maxLength={CHARACTER_LIMITS.intro}
            />
            <FieldDescription>{t.introHint}</FieldDescription>
          </Field>

          <Field data-invalid={problems.has("sheet") || undefined}>
            <FieldLabel htmlFor={`${id}-sheet`}>{t.sheet}</FieldLabel>
            <Textarea
              id={`${id}-sheet`}
              value={draft.sheet}
              onChange={(event) => update({ sheet: event.target.value })}
              maxLength={CHARACTER_LIMITS.sheet}
              required
              className="min-h-48"
              {...invalid("sheet")}
            />
            <FieldDescription>{t.sheetHint}</FieldDescription>
            {error("sheet")}
          </Field>

          <Field data-invalid={problems.has("avatarUrl") || undefined}>
            <FieldLabel htmlFor={`${id}-avatar`}>{t.avatarUrl}</FieldLabel>
            <Input
              id={`${id}-avatar`}
              type="url"
              inputMode="url"
              value={draft.avatarUrl}
              onChange={(event) => update({ avatarUrl: event.target.value })}
              placeholder="https://"
              autoComplete="off"
              {...invalid("avatarUrl")}
            />
            <FieldDescription>{t.avatarUrlHint}</FieldDescription>
            {error("avatarUrl")}
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-greeting`}>{t.greeting}</FieldLabel>
            <Textarea
              id={`${id}-greeting`}
              value={draft.greeting}
              onChange={(event) => update({ greeting: event.target.value })}
              maxLength={CHARACTER_LIMITS.greeting}
            />
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-address`}>{t.userAddress}</FieldLabel>
            <Input
              id={`${id}-address`}
              value={draft.userAddress}
              onChange={(event) => update({ userAddress: event.target.value })}
              placeholder={DEFAULT_USER_ADDRESS}
              maxLength={CHARACTER_LIMITS.userAddress}
              autoComplete="off"
            />
            <FieldDescription>{t.userAddressHint}</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-language`}>{t.languageMode}</FieldLabel>
            <Select
              items={languageOptions}
              value={draft.languageMode}
              onValueChange={(value) => value && update({ languageMode: value })}
            >
              <SelectTrigger id={`${id}-language`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {languageOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field>
            <FieldLabel htmlFor={`${id}-voice`}>{t.voiceId}</FieldLabel>
            <Input
              id={`${id}-voice`}
              value={draft.voiceId}
              onChange={(event) => update({ voiceId: event.target.value })}
              maxLength={CHARACTER_LIMITS.voiceId}
              autoComplete="off"
              spellCheck={false}
            />
            <FieldDescription>{t.voiceIdHint}</FieldDescription>
          </Field>

          <Field data-invalid={problems.has("color") || undefined}>
            <FieldLabel htmlFor={`${id}-color`}>{t.color}</FieldLabel>
            <div className="flex items-center gap-2">
              {/* 系统的取色器；旁边的输入框可以直接写。取色器只认 #rrggbb，写到一半时保持上一个能用的。 */}
              <input
                type="color"
                aria-label={t.colorPicker}
                value={/^#[0-9a-fA-F]{6}$/.test(draft.color) ? draft.color.toLowerCase() : saved.color}
                onChange={(event) => update({ color: event.target.value })}
                className="h-9 w-12 shrink-0 cursor-pointer rounded-lg border border-input bg-transparent p-1"
              />
              <Input
                id={`${id}-color`}
                value={draft.color}
                onChange={(event) => update({ color: event.target.value.trim() })}
                maxLength={7}
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
                {...invalid("color")}
              />
            </div>
            <FieldDescription>{t.colorHint}</FieldDescription>
            {error("color")}
          </Field>

          <Field aria-labelledby={`${id}-birthday`} data-invalid={problems.has("birthDay") || undefined}>
            <FieldLabel id={`${id}-birthday`} htmlFor={`${id}-birth-month`}>
              {t.birthday}
            </FieldLabel>
            <div className="grid grid-cols-2 gap-3">
              <Select
                items={monthOptions}
                value={draft.birthMonth === null ? UNSET : String(draft.birthMonth)}
                onValueChange={(value) => setDraft((current) => chooseBirthMonth(current, fromOption(value)))}
              >
                <SelectTrigger id={`${id}-birth-month`} aria-label={t.birthMonth} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {monthOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                items={dayOptions}
                value={draft.birthDay === null ? UNSET : String(draft.birthDay)}
                onValueChange={(value) => update({ birthDay: fromOption(value) })}
                disabled={draft.birthMonth === null}
              >
                <SelectTrigger aria-label={t.birthDay} className="w-full" {...invalid("birthDay")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {dayOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {error("birthDay")}
          </Field>

          <Field data-invalid={problems.has("age") || undefined}>
            <FieldLabel htmlFor={`${id}-age`}>{t.age}</FieldLabel>
            <Input
              id={`${id}-age`}
              inputMode="numeric"
              value={draft.age}
              onChange={(event) => update({ age: event.target.value })}
              maxLength={4}
              autoComplete="off"
              className="w-24"
              {...invalid("age")}
            />
            {error("age")}
          </Field>

          {failure && <FailureNotice failure={failure} />}

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={saving || (mode === "edit" && !dirty)}>
              {saving && <Spinner data-icon="inline-start" />}
              {mode === "new" ? t.create : t.save}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {copy.common.cancel}
            </Button>
            {mode === "edit" && (
              <p role="status" className="text-subtitle text-muted-foreground">
                {dirty ? t.unsaved : t.saved}
              </p>
            )}
          </div>
        </FieldGroup>
      </fieldset>
    </form>
  );
}

/** 1 到 n。 */
function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i + 1);
}

/** 生日选择框的值换回草稿里的数字，「不填」是 null。 */
function fromOption(value: string | null): number | null {
  return value === UNSET || !value ? null : Number(value);
}
