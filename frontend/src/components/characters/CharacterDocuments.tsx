"use client";

import { useEffect, useState } from "react";
import { FailureNotice } from "@/components/app/FailureNotice";
import { SettingsSection } from "@/components/app/SettingsSection";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { copy } from "@/i18n";
import { deleteCharacterDocument, importCharacterDocument, listCharacterDocuments, type CharacterDocument } from "@/lib/api";
import { documentImportFailure, toFailure, type Failure } from "@/lib/failure";
import { readDocumentFile } from "@/lib/documentFile";
import { localOwnKeys } from "@/lib/localOwnKeys";
import { TrashIcon } from "@/theme/icons";

const t = copy.characterDocuments;

export function CharacterDocuments({ characterId }: { characterId: string }) {
  const { account } = useDirectory();
  const [documents, setDocuments] = useState<CharacterDocument[] | null>(null);
  const [origin, setOrigin] = useState("");
  const [text, setText] = useState("");
  const [failure, setFailure] = useState<Failure | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<CharacterDocument | null>(null);

  async function refresh() {
    setDocuments(await listCharacterDocuments(characterId));
  }
  useEffect(() => {
    let active = true;
    listCharacterDocuments(characterId).then(
      (items) => { if (active) setDocuments(items); },
      (error) => { if (active) setFailure(toFailure(error)); },
    );
    return () => { active = false; };
  }, [characterId]);

  async function submit() {
    setFailure(null);
    if (!account?.id || !localOwnKeys(account.id).embedding) {
      setFailure({ message: t.missingKey, signedOut: false, toOwnKeys: true });
      return;
    }
    if (!origin.trim() || Array.from(origin.trim()).length > 500 || !text.trim() || Array.from(text.trim()).length > 1000000) {
      setFailure({ message: t.invalid, signedOut: false });
      return;
    }
    setBusy(true);
    try {
      await importCharacterDocument(characterId, origin, text, account.id);
      await refresh();
      setText("");
      setOrigin("");
    } catch (error) {
      setFailure(documentImportFailure(error, t.missingKey, t.savedRetry));
      try { await refresh(); } catch { /* 保留原始错误 */ }
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!selected) return;
    setBusy(true);
    setFailure(null);
    try {
      await deleteCharacterDocument(characterId, selected.id);
      await refresh();
    } catch (error) { setFailure(toFailure(error)); }
    finally { setBusy(false); setSelected(null); }
  }

  return (
    <SettingsSection title={t.title}>
      {failure && <FailureNotice failure={failure} />}
      <Field><FieldLabel htmlFor="document-origin">{t.origin}</FieldLabel><Input id="document-origin" value={origin} maxLength={500} onChange={(e) => setOrigin(e.target.value)} /></Field>
      <Field><FieldLabel htmlFor="document-text">{t.text}</FieldLabel><Textarea id="document-text" value={text} onChange={(e) => setText(e.target.value)} /></Field>
      <Field><FieldLabel htmlFor="document-file">{t.file}</FieldLabel><Input id="document-file" type="file" accept=".txt,.md,text/plain,text/markdown" onChange={async (event) => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;
        try { setText(await readDocumentFile(file)); setOrigin(file.name); setFailure(null); }
        catch (error) { setFailure({ message: error instanceof Error ? error.message : t.readFailed, signedOut: false }); }
      }} /></Field>
      <Button className="self-start" disabled={busy} onClick={submit}>{busy && <Spinner data-icon="inline-start" />}{busy ? t.importing : t.import}</Button>
      {documents?.length === 0 && <p className="text-meta text-muted-foreground">{t.empty}</p>}
      {documents && documents.length > 0 && <ul className="divide-y">{documents.map((document) => <li key={document.id} className="flex items-center gap-3 py-3">
        <div className="min-w-0 flex-1"><p className="break-words">{document.origin}</p><p className="text-meta text-muted-foreground">{document.created_at ? new Date(document.created_at).toLocaleString() : t.unknownDate} · {t.counts(document.passage_count, document.embedded_passage_count)}</p></div>
        <Button variant="ghost" size="icon-sm" aria-label={t.remove(document.origin)} disabled={busy} onClick={() => setSelected(document)}><TrashIcon /></Button>
      </li>)}</ul>}
      <AlertDialog open={selected !== null} onOpenChange={(open) => { if (!open && !busy) setSelected(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{selected && t.deleteTitle(selected.origin)}</AlertDialogTitle><AlertDialogDescription>{t.deleteDescription}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel disabled={busy}>{copy.common.cancel}</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={busy} onClick={(event) => { event.preventDefault(); void remove(); }}>{busy && <Spinner data-icon="inline-start" />}{t.deleteConfirm}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </SettingsSection>
  );
}
