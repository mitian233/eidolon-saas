import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { DeployerContact } from "@/components/DeployerContact";
import { LegalFooter } from "@/components/LegalFooter";
import { copy } from "@/i18n";

import { ReportForm } from "./ReportForm";

const t = copy.report;

export const metadata = { title: copy.legal.pageTitle(t.title) };

export default function ReportPage() {
  return (
    <PageShell header={<SubpageHeader title={t.title} backHref="/" />} footer={<LegalFooter />}>
      <div className="flex flex-col gap-6">
        <p className="text-body">{t.intro}</p>
        <ReportForm />
        <DeployerContact />
      </div>
    </PageShell>
  );
}
