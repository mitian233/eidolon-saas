import type { Metadata } from "next";
import { cookies } from "next/headers";

import { getSignInOptions, isSignedIn } from "@/lib/backend";

import { Landing } from "../Landing";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

/** `/about`：和 `/` 同一个落地页，但不把已登录的用户送走（设置页的「关于」到这里），入口换成「继续」。 */
export default async function About() {
  const [signedIn, signInOptions] = await Promise.all([
    isSignedIn((await cookies()).toString()),
    getSignInOptions(),
  ]);
  return <Landing isSignedIn={signedIn} signInOptions={signInOptions} />;
}