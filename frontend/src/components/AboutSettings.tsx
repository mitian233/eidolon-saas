import { SettingsRow } from "@/components/settings/SettingsRow";
import { copy } from "@/i18n";
import { REPOSITORY_URL } from "@/lib/repository";

const t = copy.settings.about;

/**
 * 设置「关于」：「关于 Eidolon-SaaS」、GitHub 仓库、隐私政策、使用条款四行，下面一行 Meta 字号的免责声明（应用里只有这一处）。
 * GitHub 仓库在新标签页打开，通话照常；另外三行在本页打开、离开导航外壳，通话中先问。
 */
export function AboutSettings() {
  return (
    <div className="flex flex-col">
      <ul className="-mx-4">
        <li>
          <SettingsRow href="/about" label={t.site} chevron="always" />
        </li>
        <li>
          <SettingsRow href={REPOSITORY_URL} label={t.repository} isExternal />
        </li>
        <li>
          <SettingsRow href="/privacy" label={t.privacy} chevron="always" />
        </li>
        <li>
          <SettingsRow href="/terms" label={t.terms} chevron="always" />
        </li>
      </ul>
      <p className="py-4 text-meta text-muted-foreground">{t.disclaimer}</p>
    </div>
  );
}
