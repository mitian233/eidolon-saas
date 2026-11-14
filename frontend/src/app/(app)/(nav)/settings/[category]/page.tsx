import { SettingsCategoryPage } from "@/components/settings/SettingsCategoryPage";
import { SETTINGS_CATEGORIES, type SettingsCategory } from "@/lib/settingsCategory";

// 只有这几类；不认识的 `/settings/<xxx>` 在 proxy 里就换成了 `/settings`，到不了这里。
export const dynamicParams = false;

export function generateStaticParams() {
  return SETTINGS_CATEGORIES.map((category) => ({ category }));
}

/** 设置一类的二级页面（`/settings/<类别>`）。 */
export default async function SettingsCategoryRoute({ params }: { params: Promise<{ category: string }> }) {
  const { category } = await params;
  return <SettingsCategoryPage category={category as SettingsCategory} />;
}
