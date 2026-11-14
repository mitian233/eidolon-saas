// Match the backend request limit; reject before reading the file into memory.
export const MAX_DOCUMENT_FILE_BYTES = 12_100_000;

export async function readDocumentFile(file: Pick<File, "size" | "text">): Promise<string> {
  if (file.size > MAX_DOCUMENT_FILE_BYTES) throw new RangeError("文件超过 12100000 字节上限。");
  const text = await file.text();
  if (Array.from(text.trim()).length > 1_000_000) throw new RangeError("资料文本最多 1000000 字。");
  return text;
}
