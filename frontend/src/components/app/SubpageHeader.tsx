"use client";

import NextLink from "next/link";
import type { MouseEventHandler, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { copy } from "@/i18n";
import { cn } from "@/lib/utils";
import { BackIcon } from "@/theme/icons";

type Props = {
  title: string;
  /** 返回键去哪里；不传就没有返回键。 */
  backHref?: string;
  /** 点返回键时先过一遍，例如导航外壳的 `guard`：通话中去另一位角色的对话先问会不会挂断。 */
  onBackClick?: MouseEventHandler<HTMLAnchorElement>;
  /** 返回键只在手机上：设置的二级页面在电脑上和一级列表并排，用不着返回。 */
  isBackNarrowOnly?: boolean;
  /** 页首末端的操作。 */
  end?: ReactNode;
};

/** 页面里一节的标题：语义上是 h2，字号和页首标题一样（Header name），靠字重和留白分层。 */
export function SectionHeading({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="text-header">
      {children}
    </h2>
  );
}

/** 设置的二级页面、静态页的页首：返回键、标题和末端操作。放在 PageShell 的 header 里。 */
export function SubpageHeader({ title, backHref, onBackClick, isBackNarrowOnly = false, end }: Props) {
  return (
    <div className="flex w-full items-center gap-2">
      {backHref && (
        <Button
          variant="ghost"
          size="icon-lg"
          aria-label={copy.common.back}
          nativeButton={false}
          render={<NextLink href={backHref} onClick={onBackClick} />}
          className={cn("-ml-2", isBackNarrowOnly && "md:hidden")}
        >
          <BackIcon />
        </Button>
      )}
      <h1 className="min-w-0 flex-1 truncate text-header">{title}</h1>
      {end}
    </div>
  );
}
