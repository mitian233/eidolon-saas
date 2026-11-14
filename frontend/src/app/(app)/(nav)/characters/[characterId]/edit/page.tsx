"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { CharacterDocuments } from "@/components/characters/CharacterDocuments";
import { CharacterForm } from "@/components/characters/CharacterForm";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { deleteCharacter, updateCharacter, type Character } from "@/lib/api";
import { toDraft } from "@/lib/characterDraft";
import { toFailure, type Failure } from "@/lib/failure";
import { TrashIcon } from "@/theme/icons";

const t = copy.characterForm;

/**
 * 编辑一位角色（`/characters/<id>/edit`）：在导航外壳里，归「对话」。她的设置取自外壳载入的角色目录，
 * 存好留在这一页；取消和返回都回到她的对话。表单下面是删除：入口 outline，确认框里的那一下是挂断红，
 * 删掉后回到对话列表。
 */
export default function EditCharacterPage() {
  const { characterId } = useParams<{ characterId: string }>();
  const { characters, failure, characterSaved, go, guard } = useDirectory();
  const character = characters?.find((c) => c.id === characterId);
  const conversation = `/conversation/${encodeURIComponent(characterId)}`;
  // 删掉之后目录里没有她了：走之前不显示「没有找到」。
  const [deleted, setDeleted] = useState(false);

  if (deleted || (characters === null && !failure)) {
    return (
      <PageShell isInShell width="full">
        <div className="flex flex-1 items-center justify-center p-6">
          <Spinner className="size-6 text-muted-foreground" aria-label={t.loading} />
        </div>
      </PageShell>
    );
  }
  if (!character) {
    return (
      <PageShell isInShell width="full">
        <Empty className="flex-1">
          <EmptyHeader>
            <EmptyTitle>{failure ? t.loadFailed : t.notFound}</EmptyTitle>
            {failure && <EmptyDescription>{failure.message}</EmptyDescription>}
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => go("/conversations")}>
              {t.backToList}
            </Button>
          </EmptyContent>
        </Empty>
      </PageShell>
    );
  }

  return (
    <PageShell isInShell header={
        <SubpageHeader title={t.editTitle(character.name)} backHref={conversation} onBackClick={guard(conversation)} />
      }>
      <div className="flex flex-col gap-8">
        <CharacterForm
          key={character.id}
          initial={toDraft(character)}
          mode="edit"
          onSave={async (input) => {
            const saved = await updateCharacter(character.id, input);
            characterSaved(saved);
            return saved;
          }}
          onCancel={() => go(conversation)}
        />
        <Separator />
        <CharacterDocuments characterId={character.id} />
        <DeleteCharacter character={character} onDeleted={() => setDeleted(true)} />
      </div>
    </PageShell>
  );
}

function DeleteCharacter({ character, onDeleted }: { character: Character; onDeleted: () => void }) {
  const router = useRouter();
  const { characterDeleted } = useDirectory();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);

  async function remove() {
    setBusy(true);
    setFailure(null);
    try {
      await deleteCharacter(character.id);
    } catch (e) {
      setFailure(toFailure(e));
      setBusy(false);
      setConfirming(false);
      return;
    }
    onDeleted();
    // 后端已经挂断了和她的通话：外壳里她的那一份直接结束，不再问要不要挂断。
    characterDeleted(character.id);
    router.push("/conversations");
  }

  return (
    <section className="flex flex-col gap-3">
      {failure && <FailureNotice failure={failure} />}
      <Button variant="outline" className="self-start" onClick={() => setConfirming(true)}>
        <TrashIcon data-icon="inline-start" />
        {t.delete}
      </Button>
      <AlertDialog open={confirming} onOpenChange={(open) => !busy && setConfirming(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.deleteTitle(character.name)}</AlertDialogTitle>
            <AlertDialogDescription>{t.deleteDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{copy.common.cancel}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" disabled={busy} onClick={remove}>
              {busy && <Spinner data-icon="inline-start" />}
              {t.deleteConfirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
