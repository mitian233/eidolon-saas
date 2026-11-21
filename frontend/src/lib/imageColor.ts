// 从角色的印象色推出一套能用在界面上的颜色（GLOSSARY.md「印象色」）。
// 印象色的深浅不一，直接拿来当底色或字色，
// 总有一种模式下看不清。所以这里按「底色 + 放在上面的字或图标」成对给出颜色，
// 浅色、深色模式各一份，保持色相，按 OKLCH 调明度和彩度，并用 WCAG 对比度校验每一对。

/** 纸面和墨水：主题里的底色和正文色，两边共用，校验对比度时以它们为准。 */
export const paperColors = {
  body: { light: "#fbfcfe", dark: "#14171d" },
  ink: { light: "#1c2a4a", dark: "#e3e9f5" },
} as const;

/** 主题的 `--muted`（shadcn neutral 的 oklch 0.97 / 0.269），统计里排行条的底。 */
export const mutedColors = { light: "#f5f5f5", dark: "#262626" } as const;

/** 分享图（固定浅色）排行条的底，同主题的 `--share-track`。 */
export const shareTrack = "#e8e7e2";

export type ModePair = { light: string; dark: string };

export type ImageColorScale = {
  /** 官方原色。 */
  raw: string;
  /** 属于她的小记号（头像描边、对话列表上没看过的搭话的圆点等）：和纸面、`--muted` 底（列表的选中行、悬停行）
   *  对比度都 ≥ 3，太浅就压暗、太暗就提亮。按 `--muted` 校验就够了：两种模式下它都比纸面更接近记号的明暗。 */
  mark: ModePair;
  /** 统计里属于她的排行条：和条的底（`--muted`）对比度 ≥ 3，原色够就用原色。 */
  bar: ModePair;
  /** 她的对话壁纸：她色相的极淡底；上面放新主题的 --foreground 和 --muted-foreground（都 ≥ 4.5）。 */
  wall: ModePair;
  /** 她颜色的圆按钮（通话、发送）：底色和图标色。浅色模式用原色（图标保证可辨认）；
   *  深色模式下原色可能和页面一样暗，改用与页面对比度 ≥ 3 的 mark。 */
  button: { bg: ModePair; fg: ModePair };
  /** 分享图（固定浅色，只有一份）。banner、onBanner：页首铺满的色带和上面的字，底是原色；原色上白字 ≥ 4.5 就用白字，
   *  否则用浅色的 button.fg（同色相的深色）。不用 accent 填底：浅色印象色会被压成灰色。
   *  bar：前 3 的排行条，和条的底（`shareTrack`）对比度 ≥ 3，原色够就用原色。 */
  share: { banner: string; onBanner: string; bar: string };
  /** 在纸面上写她颜色的字，以及强调色（注入成 shadcn 的 --primary，给按钮等填底）。 */
  accent: ModePair;
  /** 放在 accent 填底上的字和图标。 */
  onAccent: ModePair;
  /** 通话层渐变和底部压暗的终点、收起后通话条的底（通话层永远是深色，只有一份）；上面的白字 ≥ 7。 */
  call: { deep: string };
};

type Oklch = { l: number; c: number; h: number };

const AA = 4.5;
const GRAPHIC = 3;
/** 通话层次要字的白色不透明度，与 CallLayer 里的 `text-white/80` 一致（DESIGN.md「Call layer」）。 */
export const CALL_MUTED = 0.8;

/** 按规整后的原色记下推算结果：界面每次渲染都要取她的颜色，逐级搜索明度太慢，通话中会卡住立绘。 */
const scales = new Map<string, ImageColorScale>();

export function imageColorScale(hex: string): ImageColorScale {
  const raw = normalizeHex(hex);
  let scale = scales.get(raw);
  if (!scale) scales.set(raw, (scale = deriveScale(raw)));
  return scale;
}

function deriveScale(raw: string): ImageColorScale {
  const base = toOklch(raw);
  const at = (l: number, c: number) => fromOklch({ l, c: Math.min(c, base.c), h: base.h });
  const { body } = paperColors;

  const wall = { light: at(0.955, 0.018), dark: at(0.2, 0.016) };
  const callDeep = at(0.26, base.c * 0.45);
  const mark = {
    light: contrast(raw, mutedColors.light) >= GRAPHIC ? raw : readableOn(base, mutedColors.light, GRAPHIC, 0.16),
    dark: contrast(raw, mutedColors.dark) >= GRAPHIC ? raw : readableOn(base, mutedColors.dark, GRAPHIC, 0.14),
  };
  // 排行条的底也是 --muted，校验和记号一样。
  const bar = mark;
  const buttonBg = { light: raw, dark: mark.dark };
  const accent = { light: readableOn(base, body.light, AA, 0.16), dark: readableOn(base, body.dark, AA, 0.14) };
  const buttonFg = { light: readableOn(base, buttonBg.light, AA, 0.14), dark: readableOn(base, buttonBg.dark, AA, 0.14) };
  return {
    raw,
    mark,
    bar,
    wall,
    button: { bg: buttonBg, fg: buttonFg },
    share: {
      banner: raw,
      onBanner: contrast(raw, "#ffffff") >= AA ? "#ffffff" : buttonFg.light,
      bar: contrast(raw, shareTrack) >= GRAPHIC ? raw : readableOn(base, shareTrack, GRAPHIC, 0.16),
    },
    accent,
    onAccent: { light: mostReadable(accent.light), dark: mostReadable(accent.dark) },
    call: { deep: callDeep },
  };
}

/** 两个颜色在 OKLab 中的距离；大约 0.02 以下肉眼就分不太出来。 */
export function distance(a: string, b: string): number {
  const [x, y] = [toOklch(a), toOklch(b)];
  return Math.hypot(
    x.l - y.l,
    x.c * Math.cos(x.h) - y.c * Math.cos(y.h),
    x.c * Math.sin(x.h) - y.c * Math.sin(y.h),
  );
}

/** WCAG 2 对比度。 */
export function contrast(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** a 以 weight 的比例叠在 b 上的颜色（sRGB 线性混合，和 CSS color-mix in srgb 一致）。 */
export function mix(a: string, b: string, weight: number): string {
  const [x, y] = [toRgb(a), toRgb(b)];
  return toHex(x.map((v, i) => v * weight + y[i] * (1 - weight)));
}

/** 纸面色、墨水色、黑白里在 bg 上最清楚的一个。 */
function mostReadable(bg: string): string {
  const candidates = [paperColors.body.light, paperColors.ink.light, paperColors.body.dark, paperColors.ink.dark];
  return candidates.reduce((best, c) => (contrast(c, bg) > contrast(best, bg) ? c : best));
}

/** 与 against 对比度达到 ratio 的她的颜色：底色亮就往暗找，底色暗就往亮找。 */
function readableOn(base: Oklch, against: string, ratio: number, maxC: number): string {
  return luminance(against) > 0.18
    ? darkenUntil(base, against, ratio, maxC)
    : lightenUntil(base, against, ratio, maxC);
}

function darkenUntil(base: Oklch, against: string, ratio: number, maxC: number): string {
  for (let l = Math.min(base.l, 0.7); l > 0.05; l -= 0.01) {
    const hex = fromOklch({ l, c: Math.min(base.c, maxC), h: base.h });
    if (contrast(hex, against) >= ratio) return hex;
  }
  return "#000000";
}

function lightenUntil(base: Oklch, against: string, ratio: number, maxC: number): string {
  for (let l = Math.max(base.l, 0.5); l < 1; l += 0.01) {
    const hex = fromOklch({ l, c: Math.min(base.c, maxC), h: base.h });
    if (contrast(hex, against) >= ratio) return hex;
  }
  return "#ffffff";
}

function normalizeHex(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`印象色应为 #rrggbb：${hex}`);
  return `#${m[1].toLowerCase()}`;
}

function toRgb(hex: string): [number, number, number] {
  const n = parseInt(normalizeHex(hex).slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255) as [number, number, number];
}

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const fromLinear = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex).map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function toOklch(hex: string): Oklch {
  const [r, g, b] = toRgb(hex).map(toLinear);
  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m_ = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s_ = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const A = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;
  return { l: L, c: Math.hypot(A, B), h: Math.atan2(B, A) };
}

/** CSS 写法的 `oklch(l c h)`（色相是角度）转成 `#rrggbb`，例如读主题里的颜色。 */
export function oklchToHex(l: number, c: number, hueDegrees: number): string {
  return fromOklch({ l, c, h: (hueDegrees * Math.PI) / 180 });
}

/** OKLCH 转 sRGB；超出色域时降低彩度直到落入色域。 */
function fromOklch({ l, c, h }: Oklch): string {
  for (let chroma = c; chroma >= 0; chroma -= 0.002) {
    const rgb = oklabToRgb(l, chroma * Math.cos(h), chroma * Math.sin(h));
    if (rgb.every((v) => v >= -1e-4 && v <= 1 + 1e-4)) return toHex(rgb);
  }
  return toHex(oklabToRgb(l, 0, 0));
}

function oklabToRgb(L: number, A: number, B: number): number[] {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map(fromLinear);
}

function toHex(rgb: number[]): string {
  return `#${rgb
    .map((v) => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, "0"))
    .join("")}`;
}
