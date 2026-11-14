import { copy } from "@/i18n";
import { eventText } from "@/lib/conversationEvents";
import type { Preview } from "@/lib/conversationList";

import { EVENT_ICONS } from "./EventIcon";

const t = copy.conversationList;

/**
 * 一段对话的最后一句（`previewOf`）：她说的原样（字幕），自己说的加「你：」，对话事件是图标加原文，
 * 还没有话时写「新的对话，还没有说话」。对话列表的行和历史对话面板的行共用；截断由外面那一行管。
 */
export function PreviewText({ preview, name }: { preview: Preview; name: string }) {
  if (preview.from === "event") {
    const Icon = EVENT_ICONS[preview.event];
    return (
      <>
        <Icon aria-hidden className="mr-1 inline size-3.5 align-middle" />
        {eventText(preview, name)}
      </>
    );
  }
  if (preview.from === "you") return t.you(preview.text);
  if (preview.from === "her") return preview.text;
  return t.nothingSaidYet;
}
