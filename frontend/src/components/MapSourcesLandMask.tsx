/**
 * Land-mask method section of /map-sources (ODbL 4.6). Renders from the same
 * JSON as seo/render-map-sources.js. Inline syntax in the JSON text:
 * [text](url), `code`, **bold**.
 */
import { Fragment } from "react";
import data from "../content/basemapSources.json";

type L = "en" | "pl" | "de" | "fr";
type Tr = Record<L, string>;
type Block = { type: "p"; text: string } | { type: "ul" | "ol"; items: string[] };
const M = (data as unknown as { landMask: { h: Tr; intro: Tr; note: Tr; method: Block[] } }).landMask;

function Inline({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*)/);
  return (
    <>
      {parts.map((part, i) => {
        let m = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
        if (m) {
          return <a key={i} href={m[2]} rel="noopener" className="text-[#22d3ee] hover:underline break-words">{m[1]}</a>;
        }
        m = /^`([^`]+)`$/.exec(part);
        if (m) return <code key={i}>{m[1]}</code>;
        m = /^\*\*([^*]+)\*\*$/.exec(part);
        if (m) return <strong key={i}>{m[1]}</strong>;
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

export function LandMaskSection({ lang }: { lang: L }) {
  return (
    <section>
      <h2 id="land-mask-method" className="text-white text-base font-semibold mt-8 mb-2 scroll-mt-6">{M.h[lang]}</h2>
      <p><Inline text={M.intro[lang]} /></p>
      {M.note[lang] && <p className="mt-2 text-white/50">{M.note[lang]}</p>}
      {M.method.map((b, i) =>
        b.type === "p" ? (
          <p key={i} className="mt-2"><Inline text={b.text} /></p>
        ) : b.type === "ol" ? (
          <ol key={i} className="mt-2 ml-5 list-decimal">
            {b.items.map((it, j) => <li key={j}><Inline text={it} /></li>)}
          </ol>
        ) : (
          <ul key={i} className="mt-2 ml-5 list-disc">
            {b.items.map((it, j) => <li key={j}><Inline text={it} /></li>)}
          </ul>
        ),
      )}
    </section>
  );
}
