import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { getSignInOptions, isSignedIn } from "@/lib/backend";

import { Landing } from "./Landing";

/**
 * `/`：访客看到落地页；已登录的用户直接进对话列表。没有会话 cookie 时不问后端，保住访客的首屏；
 * 会话已经过期的，照常看到落地页，在这里重新登录。角色是私有的，访客页不读角色名单。
 */
export default async function Home() {
  if (await isSignedIn((await cookies()).toString())) redirect("/conversations");
  const signInOptions = await getSignInOptions();
  return <Landing isSignedIn={false} signInOptions={signInOptions} />;
}