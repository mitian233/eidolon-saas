"use client";

import { useId, useRef, useState, type ChangeEvent } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { SettingsSection } from "@/components/app/SettingsSection";
import { useSettingsValues } from "@/components/settings/SettingsValues";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { checkDataPackageExport, getProfile, importDataPackage, listMemories } from "@/lib/api";
import {
  CATEGORIES,
  choose,
  chosenCategories,
  exportHref,
  importSummary,
  packageFailure,
  readManifest,
  selectAll,
  type Category,
  type Choice,
} from "@/lib/dataPackage";
import { type Failure } from "@/lib/failure";
import { toDraft } from "@/lib/producerProfile";
import { SuccessIcon } from "@/theme/icons";

const t = copy.settings.dataPackage;

/**
 * 数据包（GLOSSARY.md「数据包」）：上半导出，勾要带的几类、点「导出」先问后端能不能导，能导就让浏览器直接下载、被拒就在这里说一句；下半导入，选了文件先读开头的
 * manifest.json，按包里有的几类列勾选框，点「导入」把文件原样传上去，完了说一句结果，并刷新受影响的数据。
 */
export function DataPackageSettings() {
  return (
    <>
      <ExportSection />
      <ImportSection />
    </>
  );
}

function ExportSection() {
  const [choice, setChoice] = useState<Choice>(() => selectAll(CATEGORIES));
  const [checking, setChecking] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const categories = chosenCategories(choice);

  async function start() {
    setChecking(true);
    setFailure(null);
    try {
      await checkDataPackageExport(categories);
      download(exportHref(categories));
    } catch (e) {
      setFailure(packageFailure(e));
    } finally {
      setChecking(false);
    }
  }

  return (
    <SettingsSection title={t.exportTitle} description={t.exportHint}>
      {failure && <FailureNotice failure={failure} />}
      <Categories offered={CATEGORIES} choice={choice} onChange={setChoice} />
      <div className="flex flex-col items-start">
        <Button disabled={checking || categories.length === 0} onClick={start}>
          {t.export}
        </Button>
      </div>
    </SettingsSection>
  );
}

/** 让浏览器把 `href` 下载下来，页面不动，也不经过 JS 的内存。 */
function download(href: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = "";
  link.click();
}

type Picked =
  | { kind: "none" }
  | { kind: "reading"; file: File }
  | { kind: "ready"; file: File; offered: Category[] }
  | { kind: "refused"; file: File; message: string };

function ImportSection() {
  const { profileSaved, memoryCountChanged } = useSettingsValues();
  const { refresh } = useDirectory();
  const input = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<Picked>({ kind: "none" });
  const [choice, setChoice] = useState<Choice>({});
  const [importing, setImporting] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  async function pick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // 同一个文件再选一次也算
    if (!file) return;
    setSummary(null);
    setFailure(null);
    setPicked({ kind: "reading", file });
    const reading = await readManifest(file);
    if (reading.kind === "package") {
      setPicked({ kind: "ready", file, offered: reading.categories });
      setChoice(selectAll(reading.categories));
    } else {
      setPicked({ kind: "refused", file, message: t.failures[reading.kind] });
    }
  }

  async function submit() {
    if (picked.kind !== "ready") return;
    setImporting(true);
    setSummary(null);
    setFailure(null);
    try {
      const result = await importDataPackage(picked.file, chosenCategories(choice));
      setSummary(importSummary(result));
      setPicked({ kind: "none" });
      // 导入已经成功了：没刷新到档案、记忆条数、对话列表也不报失败，那几处打开时自己会再读。
      if (result.conversations > 0) refresh();
      if (result.profile) getProfile().then((saved) => profileSaved(toDraft(saved)), () => {});
      if (result.memories > 0) listMemories().then((list) => memoryCountChanged(list.length), () => {});
    } catch (e) {
      setFailure(packageFailure(e));
    } finally {
      setImporting(false);
    }
  }

  return (
    <SettingsSection title={t.importTitle} description={t.importHint}>
      {summary && (
        <Alert role="status">
          <SuccessIcon />
          <AlertTitle>{summary}</AlertTitle>
        </Alert>
      )}
      {failure && <FailureNotice failure={failure} />}
      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={input}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={pick}
        />
        <Button variant="outline" disabled={importing} onClick={() => input.current?.click()}>
          {t.chooseFile}
        </Button>
        {picked.kind !== "none" && (
          <span className="min-w-0 truncate text-subtitle text-muted-foreground">{picked.file.name}</span>
        )}
      </div>
      {picked.kind === "reading" && <p className="text-body text-muted-foreground">{t.reading}</p>}
      {picked.kind === "refused" && <FailureNotice failure={{ message: picked.message, signedOut: false }} />}
      {picked.kind === "ready" &&
        (picked.offered.length === 0 ? (
          <p className="text-body text-muted-foreground">{t.nothingToChoose}</p>
        ) : (
          <>
            <Categories offered={picked.offered} choice={choice} onChange={setChoice} />
            <div>
              <Button disabled={importing || chosenCategories(choice).length === 0} onClick={submit}>
                {importing && <Spinner data-icon="inline-start" />}
                {importing ? t.importing : t.import}
              </Button>
            </div>
          </>
        ))}
    </SettingsSection>
  );
}

/** 按清单顺序列出可选类别。 */
function Categories({
  offered,
  choice,
  onChange,
}: {
  offered: readonly Category[];
  choice: Choice;
  onChange: (choice: Choice) => void;
}) {
  const id = useId();
  return (
    <ul className="flex flex-col">
      {offered.map((category) => (
        <li key={category}>
          <label htmlFor={`${id}-${category}`} className="flex items-center gap-3 py-1.5">
            <Checkbox
              id={`${id}-${category}`}
              checked={Boolean(choice[category])}
              onCheckedChange={(checked) => onChange(choose(choice, category, checked))}
            />
            <span className="text-body">{t.categories[category]}</span>
          </label>
        </li>
      ))}
    </ul>
  );
}
