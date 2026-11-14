import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { documentImportFailure, toFailure } from "@/lib/failure";

describe("toFailure", () => {
  it("offers the own keys when the limit refused it, or the user's own key failed", () => {
    expect(toFailure(new ApiError("这一小时的回合次数已经用完了", 429))).toMatchObject({ toOwnKeys: true });
    expect(toFailure(new ApiError("你的语音合成（Fish Audio）密钥调用失败：…", 502, { code: "own_key" }))).toMatchObject({
      toOwnKeys: true,
    });
  });

  it.each([
    ["a service failed", new ApiError("LLM 出错了", 502)],
    ["it never reached the backend", new Error("网络断了")],
  ])("offers no own keys when %s", (_, error) => {
    expect(toFailure(error).toOwnKeys).toBeFalsy();
  });
});


it("only offers keys for the document API's missing-key code", () => {
  expect(documentImportFailure(new ApiError("missing", 400, { code: "embedding_key_missing" }), "配置密钥", "重试")).toMatchObject({ message: "配置密钥", toOwnKeys: true });
  expect(documentImportFailure(new ApiError("文档为空", 400), "配置密钥", "重试")).toEqual({ message: "文档为空", signedOut: false });
});
