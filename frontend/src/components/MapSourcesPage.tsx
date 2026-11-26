/**
 * /map-sources — every source of the basemap, per release, in en/pl/de/fr.
 * Renders from the SAME JSON as the server-side page (seo/render-map-sources.js):
 * src/content/basemapSources.json. Credit sentences, licence and source names
 * are English and verbatim; only descriptive text is translated.
 */
import { Fragment } from "react";
import { Helmet } from "react-helmet-async";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import data from "../content/basemapSources.json";
import { pickLang } from "./LegalPage";
import { LandMaskSection } from "./MapSourcesLandMask";

type L = "en" | "pl" | "de" | "fr";
type Tr = Record<L, string>;
interface Source {
  name: string;
  providerUrl: string;
  version?: string;
  licence: { name: string; url: string };
  credit: string;
  creditLink: { text: string; url: string } | null;
  role: Tr;
  modified: { how: Tr } | null;
  warning?: Tr;
  note?: Tr;
}
interface Release {
  ids: string[];
  current?: boolean;
  includesNextRerender?: boolean;
  notes?: Tr;
  sources: string[];
  landMaskMethodUrls?: { id: string; url: string }[];
}

const D = data as unknown as {
  attributionUrl: string;
  releases: Release[];
  sources: Record<string, Source>;
  creator: { name: Tr; nameUrl: string; org: string; orgUrl: Tr; line: Tr };
  ui: Record<L, Record<string, string>>;
};

const A = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} rel="noopener" className="text-[#22d3ee] hover:underline break-words">{children}</a>
);

/** Replace {key} placeholders in `tpl` with nodes. */
function fill(tpl: string, map: Record<string, React.ReactNode>): React.ReactNode {
  return tpl.split(/(\{\w+\})/).map((part, i) => {
    const m = /^\{(\w+)\}$/.exec(part);
    return <Fragment key={i}>{m && m[1] in map ? map[m[1]] : part}</Fragment>;
  });
}

function Credit({ s }: { s: Source }) {
  const link = s.creditLink;
  const i = link ? s.credit.indexOf(link.text) : -1;
  if (!link || i < 0) return <>{s.credit}</>;
  return (
    <>
      {s.credit.slice(0, i)}
      <A href={link.url}>{link.text}</A>
      {s.credit.slice(i + link.text.length)}
    </>
  );
}

function SourceCard({ s, lang, methods }: { s: Source; lang: L; methods?: { id: string; url: string }[] }) {
  const u = D.ui[lang];
  const Row = ({ k, children }: { k: string; children: React.ReactNode }) => (
    <>
      <dt className="text-white/50">{k}</dt>
      <dd className="mb-2 ml-0 text-white/80">{children}</dd>
    </>
  );
  return (
    <section className="my-4 rounded-lg border border-white/10 p-4">
      <h3 className="text-white text-sm font-semibold mb-2">{s.name}</h3>
      {s.warning && (
        <p className="rounded-md border border-amber-500 px-3 py-2 text-amber-400 font-semibold">{s.warning[lang]}</p>
      )}
      <dl className="m-0">
        <Row k={u.provider}><A href={s.providerUrl}>{s.providerUrl}</A></Row>
        <Row k={u.role}>{s.role[lang]}</Row>
        {s.version && <Row k={u.version}>{s.version}</Row>}
        <Row k={u.licence}><A href={s.licence.url}>{s.licence.name}</A></Row>
        <Row k={u.credit}><q style={{ quotes: "none" }}><Credit s={s} /></q></Row>
        {methods && <Row k="Land/sea mask">{methods.map((m, i) => <div key={m.id}>{i > 0 ? null : null}<A href={m.url}>{u.landMaskMethod}{methods.length > 1 ? ` — ${m.id}` : ""}</A></div>)}</Row>}
        {s.modified && <Row k={u.modified}>{u.yes} — {s.modified.how[lang]}</Row>}
      </dl>
      {s.note && <p className="mt-2 text-white/70">{s.note[lang]}</p>}
    </section>
  );
}

function ReleaseBlock({ rel, lang }: { rel: Release; lang: L }) {
  const u = D.ui[lang];
  const [first, ...rest] = rel.ids;
  const label = rel.ids.join(" / ") + (rel.includesNextRerender ? ` ${u.also}` : "");
  return (
    <section>
      <h2 id={`release-${first}`} className="text-white text-base font-semibold mt-8 mb-2 scroll-mt-6">
        {rest.map((id) => <a key={id} id={`release-${id}`} />)}
        {u.release} {label}
        {rel.current && <small className="ml-2 text-[#22d3ee]">({u.current})</small>}
      </h2>
      {rel.notes && <p className="text-white/70">{rel.notes[lang]}</p>}
      {rel.sources.map((id) => <SourceCard key={id} s={D.sources[id]} lang={lang} methods={id.startsWith("osm-") ? rel.landMaskMethodUrls : undefined} />)}
    </section>
  );
}

export function MapSourcesPage() {
  const navigate = useNavigate();
  const { i18n } = useTranslation();
  const lang = pickLang(i18n.resolvedLanguage) as L;
  const u = D.ui[lang];
  const c = D.creator;
  const canonical = "https://something-rare.com/map-sources";
  const [cur, ...older] = D.releases;

  return (
    <>
      <Helmet>
        <html lang={lang} />
        <title>{u.title}</title>
        <meta name="description" content={u.description} />
        <link rel="canonical" href={canonical} />
        <meta property="og:title" content={u.title} />
        <meta property="og:description" content={u.description} />
        <meta property="og:url" content={canonical} />
        <meta property="og:type" content="website" />
        <meta property="og:image" content="https://something-rare.com/og.jpg" />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:title" content={u.title} />
        <meta name="twitter:description" content={u.description} />
      </Helmet>
      <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center px-4 py-12">
        <main className="w-full max-w-2xl text-xs leading-relaxed text-white/80">
          <div className="mb-8">
            <button
              onClick={() => navigate("/")}
              className="text-white/60 hover:text-white/85 flex items-center gap-1 transition-colors"
            >
              ← {u.back}
            </button>
          </div>
          <h1 className="text-white text-sm font-semibold mb-4">{u.h1}</h1>
          <p>
            {fill(c.line[lang], {
              org: <A href={c.orgUrl[lang]}>{c.org}</A>,
              name: <A href={c.nameUrl}>{c.name[lang]}</A>,
            })}
          </p>
          <LandMaskSection lang={lang} />
          <p className="mt-6">{u.intro}</p>
          <p className="mt-2">{u.fullList} <A href={D.attributionUrl}>{D.attributionUrl}</A></p>
          <p className="mt-2 text-white/50">{u.creditNote}</p>
          <ReleaseBlock rel={cur} lang={lang} />
          <h2 className="text-white text-base font-semibold mt-10 mb-2">{u.earlier}</h2>
          <p className="text-white/50">{u.archiveNote}</p>
          {older.map((r) => <ReleaseBlock key={r.ids[0]} rel={r} lang={lang} />)}
          <section>
            <h2 className="text-white text-base font-semibold mt-10 mb-2">{u.endorsementHeading}</h2>
            <p>{u.endorsement}</p>
          </section>
          <p className="mt-8"><a href="/" className="text-[#22d3ee] hover:underline">← {u.back}</a></p>
        </main>
      </div>
    </>
  );
}
