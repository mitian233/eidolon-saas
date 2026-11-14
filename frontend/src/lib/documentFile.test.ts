import { describe, expect, it, vi } from "vitest";
import { MAX_DOCUMENT_FILE_BYTES, readDocumentFile } from "@/lib/documentFile";

describe("readDocumentFile", () => {
  it("rejects a file over the byte limit without reading it", async () => {
    const text = vi.fn(async () => "too late");
    await expect(readDocumentFile({ size: MAX_DOCUMENT_FILE_BYTES + 1, text })).rejects.toThrow("字节");
    expect(text).not.toHaveBeenCalled();
  });

  it("checks character count after reading and accepts a valid file", async () => {
    await expect(readDocumentFile({ size: 2, text: async () => "猫" })).resolves.toBe("猫");
    await expect(readDocumentFile({ size: 1_000_001, text: async () => "猫".repeat(1_000_001) })).rejects.toThrow("1000000 字");
  });
});
