/**
 * 生成落地页的字体子集（ADR-0016 修订）：Shippori Mincho B1（日文、拉丁字母）、Noto Serif SC（中文大标题）、
 * Noto Sans SC（中文正文），按落地页实际用到的字做成 woff2，每种另有一份只含第 0 幕文字的小子集给首屏预载，
 * 连同清单 subset.json 写进 src/app/(landing)/fonts/，一起提交。子集不在构建时生成，维护者在本地重新生成。
 *
 * 用法（在 frontend 目录）：
 *
 *     node scripts/landing-fonts.mts
 *
 * 什么时候跑：改了落地页或登录组件的文案之后。忘了跑的话，
 * 覆盖契约测试（src/app/(landing)/fonts/coverage.test.ts）会失败，并列出缺的字。
 *
 * 要的字由 fontText.ts 收集（和覆盖契约测试同一份）。源字体第一次运行时从 GitHub 下载（google/fonts、
 * notofonts/noto-cjk，都是 SIL OFL 1.1），缓存在 .cache/landing-fonts/；子集由 fontTools 的 pyftsubset
 * 生成，经 `uv run --with` 临时安装，本机要有 uv（后端也用它）。子集保留竖排（vert、vpal 等）、
 * 标点挤压（palt）和字距的 OpenType 特性，去掉 hinting。
 */

import { spawnSync } from "node:child_process";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const FRONTEND = fileURLToPath(new URL("..", import.meta.url));
const OUT = path.join(FRONTEND, "src/app/(landing)/fonts");
const CACHE = path.join(FRONTEND, ".cache/landing-fonts");
const FONTTOOLS = "fonttools[woff]==4.61.1";
/** 留下的 OpenType 特性：竖排（vert、vrt2、vpal、vhal、vkrn）、标点挤压（palt、halt）、字距和连字。
 * aalt、fwid 这类备选字形的特性页面上用不到，留着会把每个字的异体字形都拉进来，子集大一倍。 */
const FEATURES = "ccmp,locl,liga,kern,palt,halt,vert,vrt2,vpal,vhal,vkrn";

const SHIPPORI = "https://github.com/google/fonts/raw/main/ofl/shipporiminchob1";
const NOTO = "https://github.com/notofonts/noto-cjk/raw/main";

/**
 * 每种字体：源字体，和输出的文件名。每种出两份：`<名字>.woff2` 是完整子集，`<名字>-act0.woff2` 只有
 * 第 0 幕上的字，首屏只预载这一份。落地页的根 layout（layout.tsx）按这些文件名载入。
 */
const FONTS = [
  { source: `${SHIPPORI}/ShipporiMinchoB1-SemiBold.ttf`, out: "shippori-mincho-b1-600" },
  { source: `${NOTO}/Serif/SubsetOTF/SC/NotoSerifSC-SemiBold.otf`, out: "noto-serif-sc-600" },
  { source: `${NOTO}/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf`, out: "noto-sans-sc-400" },
];

const LICENSES = [
  { source: `${SHIPPORI}/OFL.txt`, out: "LICENSE-shippori-mincho-b1.txt" },
  { source: `${NOTO}/Serif/LICENSE`, out: "LICENSE-noto-serif-sc.txt" },
  { source: `${NOTO}/Sans/LICENSE`, out: "LICENSE-noto-sans-sc.txt" },
];

// fontText.ts 是应用的 TypeScript：import 不写扩展名，还用 `@/` 指 src。Node 自己去掉类型，
// 这两种写法由这个解析钩子补上。
register(
  `data:text/javascript,${encodeURIComponent(`
    const SRC = ${JSON.stringify(pathToFileURL(path.join(FRONTEND, "src/")).href)};
    export async function resolve(specifier, context, next) {
      const spec = specifier.startsWith("@/") ? SRC + specifier.slice(2) : specifier;
      try {
        return await next(spec, context);
      } catch (e) {
        if (!["ERR_MODULE_NOT_FOUND", "ERR_UNSUPPORTED_DIR_IMPORT"].includes(e.code) || !/^[.@]|^file:/.test(spec)) throw e;
        for (const suffix of [".ts", ".tsx", "/index.ts"]) {
          try { return await next(spec + suffix, context); } catch {}
        }
        throw e;
      }
    }
  `)}`,
);

const { act0Text, landingText } = await import(pathToFileURL(path.join(OUT, "fontText.ts")).href);
const text: string = landingText();
const act0: string = act0Text();

async function cached(url: string): Promise<string> {
  const file = path.join(CACHE, new URL(url).pathname.slice(1).replaceAll("/", "_"));
  try {
    await stat(file);
    return file;
  } catch {}
  console.log(`下载 ${url}`);
  // 用 curl 而不是 fetch：Node 的 fetch 不认 HTTPS_PROXY，在要走代理的机器上连不上 GitHub。
  const run = spawnSync("curl", ["-fL", "--retry", "2", "-o", `${file}.part`, url], { stdio: "inherit" });
  if (run.status !== 0) throw new Error(`下载失败：${url}`);
  await rename(`${file}.part`, file);
  return file;
}

await mkdir(CACHE, { recursive: true });

/** 用 pyftsubset 把 `source` 按 `chars` 做成 `out`。 */
async function subset(source: string, chars: string, out: string) {
  const textFile = path.join(CACHE, "text.txt");
  await writeFile(textFile, chars, "utf-8");
  const run = spawnSync(
    "uv",
    [
      "run", "--no-project", "--with", FONTTOOLS,
      "pyftsubset", source,
      `--text-file=${textFile}`,
      `--output-file=${path.join(OUT, out)}`,
      "--flavor=woff2",
      `--layout-features=${FEATURES}`,
      "--no-hinting",
      "--desubroutinize",
    ],
    { stdio: "inherit" },
  );
  if (run.status !== 0) throw new Error(`pyftsubset 没能生成 ${out}`);
  console.log(`${out}  ${((await stat(path.join(OUT, out))).size / 1024).toFixed(1)} KB`);
}

/** `file` 里实际有字形的字。pyftsubset 遇到源字体里没有的字不报错，直接丢掉。 */
function glyphs(file: string): string {
  const read = "import sys; from fontTools.ttLib import TTFont; print(''.join(map(chr, sorted(TTFont(sys.argv[1]).getBestCmap()))))";
  const run = spawnSync("uv", ["run", "--no-project", "--with", FONTTOOLS, "python", "-c", read, file], {
    encoding: "utf-8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  if (run.status !== 0) throw new Error(`读不出 ${file} 的字：${run.stderr}`);
  return [...run.stdout.trim()].filter((ch) => text.includes(ch)).join("");
}

const covered: Record<string, string> = {};
for (const font of FONTS) {
  const source = await cached(font.source);
  await subset(source, text, `${font.out}.woff2`);
  await subset(source, act0, `${font.out}-act0.woff2`);
  covered[font.out] = glyphs(path.join(OUT, `${font.out}.woff2`));
  const lacking = [...text].filter((ch) => !covered[font.out].includes(ch)).join("");
  if (lacking) console.log(`  ${font.out} 没有这些字（由字体栈里的下一种字体显示）：${lacking}`);
}

for (const license of LICENSES) {
  await writeFile(path.join(OUT, license.out), await readFile(await cached(license.source)));
}

await writeFile(
  path.join(OUT, "subset.json"),
  `${JSON.stringify(
    {
      about:
        "落地页字体子集的清单，由 scripts/landing-fonts.mts 生成，不要手改。text 是做完整子集要的字，act0 是第 0 幕那一份要的字，glyphs 是每种字体的完整子集里实际有字形的字。",
      sources: FONTS.map((f) => f.source),
      text,
      act0,
      glyphs: covered,
    },
    null,
    2,
  )}\n`,
);
console.log(`子集共 ${[...text].length} 个字，清单写在 subset.json。`);
