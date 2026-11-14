"use client";

import { characterAvatarUrl } from "@/lib/characterAvatar";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Popover, PopoverContent, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/i18n";
import { setShown, showAll } from "@/lib/listPreferences";
import { FilterIcon } from "@/theme/icons";

import { useDirectory, useWide } from "./ConversationDirectory";

const t = copy.conversationList;

type Props = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** 这台设备上隐藏的人数：按钮上的小点、读屏的名字、「全部显示」能不能点都看它。 */
  hiddenCount: number;
};

/**
 * 搜索框右边的筛选按钮和它打开的面板（DESIGN.md「Conversation list」）：宽屏是挂在按钮下面的 Popover，
 * 窄屏是从底部弹出的 Drawer。面板列出所有人，每人一行勾选框；勾选立即生效，没有确定键。
 * 有人被隐藏时，按钮右上角有一个中性色的小点。
 */
export function ListFilter({ isOpen, onOpenChange, hiddenCount }: Props) {
  const wide = useWide();
  const { tidy } = useDirectory();
  const label = hiddenCount > 0 ? t.filterHidden(String(hiddenCount)) : t.filter;
  const button = { variant: "ghost", size: "icon-lg", "aria-label": label, className: "relative" } as const;
  const icon = (
    <>
      <FilterIcon />
      {hiddenCount > 0 && (
        <span aria-hidden className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-muted-foreground" />
      )}
    </>
  );
  const showEveryone = (
    <Button variant="ghost" size="sm" disabled={hiddenCount === 0} onClick={() => tidy(showAll)}>
      {t.showAll}
    </Button>
  );

  if (wide) {
    return (
      <Popover open={isOpen} onOpenChange={onOpenChange}>
        <PopoverTrigger render={<Button {...button} />}>{icon}</PopoverTrigger>
        <PopoverContent align="end" className="max-h-[min(32rem,70dvh)]">
          <PopoverHeader className="flex-row items-center justify-between">
            <PopoverTitle>{t.filterTitle}</PopoverTitle>
            {showEveryone}
          </PopoverHeader>
          <div className="-mx-2.5 min-h-0 flex-1 overflow-y-auto px-2.5">
            <Groups />
          </div>
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <>
      <Button {...button} onClick={() => onOpenChange(true)}>
        {icon}
      </Button>
      <Drawer open={isOpen} onOpenChange={onOpenChange} showSwipeHandle>
        <DrawerContent>
          <DrawerHeader className="flex-row items-center justify-between">
            <DrawerTitle>{t.filterTitle}</DrawerTitle>
            {showEveryone}
          </DrawerHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-2 pb-4">
            <Groups />
          </div>
        </DrawerContent>
      </Drawer>
    </>
  );
}

/** 勾选清单：每人一行勾选框、小头像、名字。 */
function Groups() {
  const { characters, preferences, tidy } = useDirectory();
  if (!characters) return null;
  const hidden = preferences.hidden;
  return (
    <ul className="flex flex-col">
      {characters.map((c) => (
        <li key={c.id}>
          <label className="flex items-center gap-3 py-1.5">
            <Checkbox
              checked={!hidden.includes(c.id)}
              onCheckedChange={(checked) => tidy((p) => setShown(p, [c.id], checked))}
            />
            <span aria-hidden className="flex">
              <MarkedAvatar name={c.name} src={characterAvatarUrl(c)} size="sm" />
            </span>
            <span className="min-w-0 truncate">{c.name}</span>
          </label>
        </li>
      ))}
    </ul>
  );
}
