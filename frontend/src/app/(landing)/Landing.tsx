import { AppLink } from "@/components/app/AppLink";
import { SignInChoices } from "@/components/app/SignInChoices";
import { LegalFooter } from "@/components/LegalFooter";
import { buttonVariants } from "@/components/ui/button";
import { copy } from "@/i18n";
import type { SignInOptions } from "@/lib/api";
import { cn } from "@/lib/utils";

const t = copy.landing;

/**
 * 落地页（M0 占位版）：只说这是什么、怎么登录，不展示任何默认角色。
 * `/` 给访客登录入口；`/about` 给已登录的用户一个回到对话列表的入口。
 */
export function Landing({
  isSignedIn,
  signInOptions,
}: {
  isSignedIn: boolean;
  signInOptions: SignInOptions | null;
}) {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center p-6">
      <div className="flex w-full max-w-90 flex-col gap-6">
        <div className="flex flex-col gap-3">
          <h1 className="landing-title text-list-title">{copy.app.name}</h1>
          <p className="text-body text-muted-foreground">{copy.app.description}</p>
        </div>

        {isSignedIn ? (
          <a href="/conversations" className={cn(buttonVariants({ size: "lg" }), "w-full")}>
            {t.continue}
          </a>
        ) : (
          <>
            <SignInChoices options={signInOptions} />
            {signInOptions?.dev_login && (
              <AppLink href="/login" isStandalone className="justify-self-start">
                {copy.login.devTitle}
              </AppLink>
            )}
          </>
        )}

        <LegalFooter />
      </div>
    </main>
  );
}