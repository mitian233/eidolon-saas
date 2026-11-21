import { AppLink } from "@/components/app/AppLink";
import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { DeployerContact } from "@/components/DeployerContact";
import { LegalFooter } from "@/components/LegalFooter";
import { copy } from "@/i18n";
import { interpolate } from "@/i18n/interpolate";

const t = copy.terms;

export const metadata = { title: copy.legal.pageTitle(t.title) };

export default function TermsPage() {
  return (
    <PageShell header={<SubpageHeader title={t.title} backHref="/" />} footer={<LegalFooter />}>
      <div className="flex flex-col gap-6">
        {/* 条款一条一行：条目名加粗在上，正文在下，行间一条细分隔线（DESIGN.md「The Flat Rule」）。 */}
        <dl className="flex flex-col divide-y">
          {t.items.map((item) => (
            <div key={item.term} className="flex flex-col gap-1 py-3">
              <dt className="text-body font-semibold">{item.term}</dt>
              <dd className="text-body">{item.text}</dd>
            </div>
          ))}
        </dl>
        <p className="text-body">
          {interpolate(t.seePrivacy, {
            privacy: (
              <AppLink key="privacy" href="/privacy">
                {copy.legal.privacy}
              </AppLink>
            ),
          })}
        </p>
        <p className="text-body"><AppLink href="/report">{copy.legal.report}</AppLink></p>
        <DeployerContact />
        <p className="text-meta text-muted-foreground">{t.lastUpdated}</p>
      </div>
    </PageShell>
  );
}
