"use client";

import { AppLink } from "@/components/app/AppLink";
import { copy } from "@/i18n";
import { SOURCE_URL } from "@/lib/repository";

/**
 * 公开页面共用的站点声明与链接，窄屏可折行。
 */
export function LegalFooter() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className="text-meta text-muted-foreground">{copy.legal.disclaimer}</p>
      <nav aria-label={copy.legal.navigation} className="flex flex-wrap gap-x-3 gap-y-1">
        <AppLink href="/privacy" isStandalone isMuted>
          {copy.legal.privacy}
        </AppLink>
        <AppLink href="/terms" isStandalone isMuted>
          {copy.legal.terms}
        </AppLink>
        <AppLink href="/report" isStandalone isMuted>
          {copy.legal.report}
        </AppLink>
        <AppLink href={SOURCE_URL} target="_blank" rel="noopener noreferrer" isStandalone isMuted>
          {copy.legal.source}
        </AppLink>
      </nav>
    </div>
  );
}
