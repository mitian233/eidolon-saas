/** 这个项目的 GitHub 仓库。 */
export const REPOSITORY_URL = "https://github.com/Sallyn0225/eidolon-sc";

/** The corresponding source for this deployment, defaulting to the SaaS fork. */
export const SOURCE_URL = process.env.NEXT_PUBLIC_EIDOLON_SOURCE_URL?.trim()
  || "https://github.com/mitian233/eidolon-saas/tree/saas/main";
