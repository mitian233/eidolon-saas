import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { OwnJudgeSetting } from "@/components/OwnJudgeSetting";

it("explains why affinity does not change while judging is disabled", () => {
  const html = renderToStaticMarkup(<OwnJudgeSetting enabled={false} disabled={false} onChange={() => {}} />);
  expect(html).toContain("判断功能已关闭");
  expect(html).toContain("好感度不会变化");
  expect(html).toContain("召回靠角色自己调用工具");
});
