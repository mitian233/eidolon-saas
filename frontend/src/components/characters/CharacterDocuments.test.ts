import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("document list typography", () => {
  it("uses the registered meta token for the empty state and document metadata", () => {
    const source = readFileSync(new URL("./CharacterDocuments.tsx", import.meta.url), "utf8");
    expect(source.match(/text-meta text-muted-foreground/g)).toHaveLength(2);
    expect(source).not.toContain("text-sm text-muted-foreground");
  });
});
