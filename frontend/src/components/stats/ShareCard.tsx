"use client";

import { useMemo, type Ref } from "react";
import { encode } from "uqr";

import { copy } from "@/i18n";
import type { Character } from "@/lib/api";
import {
  SHARE_INNER_WIDTH,
  type ShareCardContent,
  type ShareTotal,
  type SiteAddress,
  type TotalSize,
} from "@/lib/shareCard";
import { heatmapMonths, heatmapWeeks, type Ranked, type Stats } from "@/lib/stats";
import { cn } from "@/lib/utils";
import { shareVars } from "@/theme/herVars";

const t = copy.settings.stats;

/** The totals' numbers at each size, and their units beside them (`lib/shareCard` 的 `unitSize`). */
const TOTAL_TEXT: Record<TotalSize, { number: string; unit: string }> = {
  120: { number: "text-share-total-xl", unit: "text-share-body" },
  100: { number: "text-share-total-lg", unit: "text-share-label" },
  80: { number: "text-share-total-md", unit: "text-share-label" },
  64: { number: "text-share-total-sm", unit: "text-share-label" },
  48: { number: "text-share-total-xs", unit: "text-share-label" },
};

/** Each shade of the small heatmap, 0 (did not come) to 4, all of the ink; as on the page. */
const SHADES = ["fill-share-ink/8", "fill-share-ink/25", "fill-share-ink/45", "fill-share-ink/70", "fill-share-ink"];
const HEAT_GAP = 3;
const MONTH_ROW = 24;
const MONTH_LABEL_WIDTH = 44; // room for 「10月」 at text-share-small

const QR_SIZE = 120;

type Props = {
  card: ShareCardContent;
  byId: Map<string, Character>;
  heatmap: Stats["heatmap"];
  site: SiteAddress;
  ref?: Ref<HTMLDivElement>;
};

/**
 * 分享图（DESIGN.md「分享图」，GLOSSARY.md「分享图」）：固定 1080×1350 px 的浅色海报，不跟深色模式，转成 PNG 下载。
 * 顶上一条主角印象色原色的色带，放她的头像、称呼和跨度标签、一句话画像、名字和罗马音；下面一排总数、聊得最多的前 3、
 * 小号热力图，最底下网站名、网址和指向落地页的二维码。画布上的像素值都是分享图专用的 token（`text-share-*`、`*-share-*`），
 * 间距刻度在画布里钉成 4px（`.share-canvas`）。
 */
export function ShareCard({ card, byId, heatmap, site, ref }: Props) {
  const hero = byId.get(card.hero);
  if (!hero) return null;
  return (
    <div
      ref={ref}
      style={shareVars(hero.color)}
      className="share-canvas flex h-[1350px] w-[1080px] flex-col overflow-hidden bg-share-paper font-sans text-share-ink"
    >
      <header className="flex items-center gap-10 bg-her-banner px-16 pt-16 pb-14 text-her-banner-fg">
        <Avatar character={hero} className="size-52 ring-6 ring-her-banner-fg" />
        <div className="flex min-w-0 flex-1 flex-col gap-2.5">
          <div className="flex items-center justify-between gap-4">
            <span className="truncate text-share-address">{card.address}</span>
            <span className="shrink-0 rounded-full border-2 border-her-banner-fg px-4.5 py-1 text-share-caption font-semibold">
              {card.span}
            </span>
          </div>
          {card.portrait && <p className="text-share-portrait">{card.portrait}</p>}
          <div className="mt-1.5 flex min-w-0 items-baseline gap-4.5 whitespace-nowrap">
            <span className="text-share-name">{hero.name}</span>
          </div>
        </div>
      </header>
      <div className="flex flex-1 flex-col px-16 py-13">
        <dl className="flex gap-8">
          {card.totals.map((total) => (
            <Total key={total.label} total={total} size={card.totalSize} />
          ))}
        </dl>
        <TopThree top={card.top} byId={byId} />
        <SmallHeatmap heatmap={heatmap} />
        <div className="flex-1" />
        <Footer site={site} />
      </div>
    </div>
  );
}

/** A total: a 4px ink rule on top, the label under it, and the number big, at the size the whole row is set in. */
function Total({ total, size }: { total: ShareTotal; size: TotalSize }) {
  const text = TOTAL_TEXT[size];
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2.5 border-t-4 border-share-ink pt-3.5">
      <dt className="text-share-label text-share-muted">{total.label}</dt>
      <dd className="flex items-baseline gap-2.5 whitespace-nowrap">
        {total.parts.map((part) => (
          <span key={part.unit ?? ""} className="inline-flex items-baseline gap-1.5">
            <span className={cn("tabular-nums", text.number)}>{part.value}</span>
            {part.unit && <span className={cn("font-semibold", text.unit)}>{part.unit}</span>}
          </span>
        ))}
      </dd>
    </div>
  );
}

/** 聊得最多的前 3：名次（第一名近黑、其余次要色）、头像、名字、她的条（长短按占第一名的比例）和「N 回合」。 */
function TopThree({ top, byId }: { top: Ranked[]; byId: Map<string, Character> }) {
  return (
    <section className="mt-14 flex flex-col gap-3.5">
      <h2 className="text-share-title">{t.mostTalked}</h2>
      <ol className="flex flex-col gap-3.5">
        {top.map((one, i) => {
          const character = byId.get(one.character_id);
          if (!character) return null;
          return (
            <li key={one.character_id} style={shareVars(character.color)} className="flex h-14 items-center gap-5.5">
              <span className={cn("w-12 text-share-rank tabular-nums", i > 0 && "text-share-muted")}>
                {String(i + 1).padStart(2, "0")}
              </span>
              <Avatar character={character} className="size-14" />
              <span className="w-42.5 truncate text-share-body font-semibold">{character.name}</span>
              <div className="h-5.5 flex-1 bg-share-track">
                <div className="h-full bg-her-bar" style={{ width: `${one.share * 100}%` }} />
              </div>
              <span className="w-37.5 text-right text-share-body font-bold whitespace-nowrap tabular-nums">
                {one.turns} <span className="text-share-caption font-medium text-share-muted">{t.share.turnsUnit}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** 小号热力图：「过去一年」和「来过 N 天」，52 周的格子铺满内容宽，不跟着跨度变。 */
function SmallHeatmap({ heatmap }: { heatmap: Stats["heatmap"] }) {
  const weeks = useMemo(() => heatmapWeeks(heatmap), [heatmap]);
  const cell = (SHARE_INNER_WIDTH - HEAT_GAP * (weeks.length - 1)) / weeks.length;
  const step = cell + HEAT_GAP;
  const months = heatmapMonths(weeks, Math.ceil(MONTH_LABEL_WIDTH / step));
  const cameOn = heatmap.counts.filter((n) => n > 0).length;
  return (
    <section className="mt-12 flex flex-col gap-2.5">
      <div className="flex items-baseline gap-4">
        <h2 className="text-share-title">{t.heatmap}</h2>
        <span className="text-share-caption text-share-muted">{t.cameOn(cameOn)}</span>
      </div>
      <svg width={SHARE_INNER_WIDTH} height={MONTH_ROW + step * 7 - HEAT_GAP} className="block text-share-small">
        {[...months].map(([column, label]) => (
          <text key={column} x={column * step} y={17} className="fill-share-muted">
            {label}
          </text>
        ))}
        {weeks.map((week, column) =>
          week.map((day, row) => (
            <rect
              key={day.date}
              x={column * step}
              y={MONTH_ROW + row * step}
              width={cell}
              height={cell}
              rx={2}
              className={SHADES[day.level]}
            />
          )),
        )}
      </svg>
    </section>
  );
}

/** 页脚：细线下面左边网站名和一句介绍，右边去掉协议的网址和指向落地页的二维码（纠错级别 M，不留白边）。 */
function Footer({ site }: { site: SiteAddress }) {
  const qr = useMemo(() => encode(site.landing, { ecc: "M", border: 0 }), [site.landing]);
  const modules = qr.data.flatMap((row, y) => row.flatMap((on, x) => (on ? [`M${x} ${y}h1v1h-1z`] : []))).join("");
  return (
    <footer className="flex items-end gap-6 border-t border-share-rule pt-7">
      <div className="flex flex-1 flex-col gap-1.5">
        <span className="text-share-site">{copy.app.name}</span>
        <span className="text-share-caption text-share-muted">{copy.app.description}</span>
      </div>
      <span className="pb-1 text-share-caption text-share-muted">{site.shown}</span>
      <svg
        width={QR_SIZE}
        height={QR_SIZE}
        viewBox={`0 0 ${qr.size} ${qr.size}`}
        shapeRendering="crispEdges"
        className="block shrink-0"
      >
        <path d={modules} className="fill-share-ink" />
      </svg>
    </footer>
  );
}

/** 她的圆头像；图没有时是排行条底色的圆。 */
function Avatar({ character, className }: { character: Character; className: string }) {
  return (
    <div className={cn("shrink-0 overflow-hidden rounded-full bg-share-track", className)}>
      {character.avatar_url && <img src={character.avatar_url} alt="" className="size-full object-cover" />}
    </div>
  );
}
