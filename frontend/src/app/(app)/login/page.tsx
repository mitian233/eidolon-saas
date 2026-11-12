"use client";

import { FormEvent, useEffect, useState } from "react";

import { FailureNotice } from "@/components/app/FailureNotice";
import { PageShell } from "@/components/app/PageShell";
import { SignInChoices } from "@/components/app/SignInChoices";
import { SectionHeading } from "@/components/app/SubpageHeader";
import { LegalFooter } from "@/components/LegalFooter";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copy } from "@/i18n";
import { devLogin, getSignInOptions, isSignedInHere, type SignInOptions } from "@/lib/api";
import { toFailure, type Failure } from "@/lib/failure";
import { signInFailure } from "@/lib/signIn";
import { FailureIcon } from "@/theme/icons";

const t = copy.login;

/**
 * 登录页：登录被拒时后端带着 `?error=` 回到这里，开发登录也在这里，也可以直接访问。访客平常在落地页的登录面板登录。
 * 邀请链接也指向这里（`?invite=`），链接里的码随登录带给后端；已经登录的人打开它直接进对话列表。
 */
export default function LoginPage() {
  const [options, setOptions] = useState<SignInOptions | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [invite, setInvite] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setRefusal(query.get("error"));
    const code = query.get("invite");
    setInvite(code);
    // 已经登录的人打开邀请链接，用不上它，照常进对话列表。
    if (code) isSignedInHere().then((yes) => yes && window.location.replace("/conversations"), () => {});
    getSignInOptions().then(setOptions, (e) => setFailure(toFailure(e)));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailure(null);
    try {
      await devLogin(name.trim());
      window.location.assign("/conversations");
    } catch (e) {
      setFailure(toFailure(e));
    }
  }

  const refusalText = refusal ? signInFailure(refusal, options?.contact) : null;

  return (
    <PageShell footer={<LegalFooter />}>
      <div className="flex flex-col gap-8 py-2">
        <div className="flex flex-col gap-3">
          <h1 className="text-list-title">{copy.app.name}</h1>
          <p className="text-body">{t.lede}</p>
        </div>

        {/* 登录被拒绝：和 FailureNotice 一样用中性的 Alert 加警示图标，挂断红只给挂断和删除、封禁（DESIGN.md「Tertiary」）。 */}
        {refusal && (
          <Alert>
            <FailureIcon />
            <AlertTitle>{t.refusedTitle}</AlertTitle>
            {refusalText && <AlertDescription>{refusalText}</AlertDescription>}
          </Alert>
        )}

        <SignInChoices options={options} invite={invite} className="max-w-90" />

        {options?.dev_login && (
          <form onSubmit={submit} className="flex max-w-90 flex-col gap-3">
            <div className="flex flex-col gap-1">
              <SectionHeading>{t.devTitle}</SectionHeading>
              <p className="text-body text-muted-foreground">{t.devHint}</p>
            </div>
            <div className="flex items-center gap-2">
              <Input aria-label={t.devName} value={name} onChange={(e) => setName(e.target.value)} className="flex-1" />
              <Button type="submit" disabled={!name.trim()}>
                {t.devSubmit}
              </Button>
            </div>
          </form>
        )}

        {failure && <FailureNotice failure={failure} />}

      </div>
    </PageShell>
  );
}
