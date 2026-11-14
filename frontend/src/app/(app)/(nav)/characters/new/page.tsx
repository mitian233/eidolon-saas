"use client";

import { FailureNotice } from "@/components/app/FailureNotice";
import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { CharacterForm } from "@/components/characters/CharacterForm";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Spinner } from "@/components/ui/spinner";
import { copy } from "@/i18n";
import { createCharacter } from "@/lib/api";
import { EMPTY_DRAFT } from "@/lib/characterDraft";

/** 新建角色（`/characters/new`）：在导航外壳里，归「对话」。建好就去和她的对话，取消回对话列表。 */
export default function NewCharacterPage() {
  const { characters, failure, characterSaved, go, guard } = useDirectory();

  // 角色目录还没载入（或没能载入）时不让建：建好的她要加进目录，目录还没有就加不进去，跳过去也找不到她。
  const header = (
    <SubpageHeader title={copy.characterForm.newTitle} backHref="/conversations" onBackClick={guard("/conversations")} />
  );
  if (characters === null) {
    return (
      <PageShell isInShell header={header}>
        {failure ? (
          <FailureNotice failure={failure} />
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <Spinner className="size-6 text-muted-foreground" aria-label={copy.characterForm.loading} />
          </div>
        )}
      </PageShell>
    );
  }

  return (
    <PageShell isInShell header={header}>
      <CharacterForm
        initial={EMPTY_DRAFT}
        mode="new"
        onSave={async (input) => {
          const character = await createCharacter(input);
          characterSaved(character);
          go(`/conversation/${encodeURIComponent(character.id)}`);
          return character;
        }}
        onCancel={() => go("/conversations")}
      />
    </PageShell>
  );
}
