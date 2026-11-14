import type { Character } from "@/lib/api";

export function characterAvatarUrl(character: Character | null | undefined): string | null {
  return character?.avatar_url ? `/api/characters/${encodeURIComponent(character.id)}/avatar` : null;
}
