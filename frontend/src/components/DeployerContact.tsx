"use client";

import { useEffect, useState } from "react";

import { SectionHeading } from "@/components/app/SubpageHeader";
import { copy } from "@/i18n";
import { getSignInOptions } from "@/lib/api";

/** Deployment contact, shown only when configured. */
export function DeployerContact({ forPrivacy = false }: { forPrivacy?: boolean }) {
  const [contact, setContact] = useState<string | null>(null);

  useEffect(() => {
    getSignInOptions().then(
      (options) => setContact(options.contact),
      () => {},
    );
  }, []);

  if (!contact) return null;
  return (
    <section className="flex flex-col gap-3">
      <SectionHeading>{forPrivacy ? copy.privacy.contact.title : copy.report.directContact}</SectionHeading>
      <p className="text-body wrap-anywhere">{forPrivacy ? copy.privacy.contact.text(contact) : contact}</p>
    </section>
  );
}
