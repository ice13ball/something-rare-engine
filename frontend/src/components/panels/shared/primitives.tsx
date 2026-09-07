// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { SourceLink } from "../../../utils/sourceUrl";
import { T } from "./tokens";

export function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 border-b border-white/5 last:border-0">
      <span className={T.rowLabel}>{label}</span>
      <span className={T.rowValue}>{value}</span>
    </div>
  );
}

// Small "i" glyph with a native hover tooltip — used to explain how to read a
// flagged value (e.g. the depth-adaptive oxygen/pH thresholds on the Argo panel).
export function InfoHint({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="ml-1 inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-white/25 text-white/70 text-[9px] leading-none cursor-help align-middle"
    >
      i
    </span>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className={T.sectionH}>{title}</p>
      {children}
    </div>
  );
}

export function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-block ${T.badge} border rounded px-1.5 py-0.5 mb-2 ${color}`}>
      {label}
    </span>
  );
}

export function PanelHeader({ children }: { children: React.ReactNode }) {
  return <h2 className={T.header}>{children}</h2>;
}

export function Subtitle({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <p className={`${T.subtitle} ${className}`}>{children}</p>;
}

export function BodyText({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <p className={`${T.body} ${className}`}>{children}</p>;
}

export function HintText({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <p className={`${T.hint} ${className}`}>{children}</p>;
}

export function WarningBanner({ children, color = "red" }: { children: React.ReactNode; color?: "red" | "orange" }) {
  const bg = color === "red" ? "bg-red-500/10 border-red-500/20" : "bg-orange-500/10 border-orange-500/20";
  const text = color === "red" ? "text-red-400" : "text-orange-400";
  return (
    <div className={`mb-3 px-2 py-1.5 rounded-lg ${bg} border`}>
      <p className={`${text} ${T.warning}`}>{children}</p>
    </div>
  );
}

export function SourceFooter({ children }: { children: React.ReactNode }) {
  return <p className={T.source}>{children}</p>;
}

/**
 * Renders a "Source: <Org name> ↗" footer line where the org name is a clickable
 * link — to the per-feature page when the source has stable IDs, otherwise to
 * the organisation homepage. Use sourceLinkFor("<key>", p) for most layers, or
 * offshoreSourceLink(p) for offshore-activities (16-source dispatch). When
 * `link` is null (unknown key — should never happen in practice), falls back
 * to the legacy text-only SourceFooter via the `fallback` prop.
 */
export function SourceAttribution({ link, fallback }: { link: SourceLink | null; fallback?: React.ReactNode }) {
  if (!link) return fallback != null ? <SourceFooter>{fallback}</SourceFooter> : null;
  return (
    <p className={T.source}>
      Source:{" "}
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        className="underline decoration-white/20 hover:decoration-white/60 hover:text-white/85 transition-colors"
        title={link.isDeepLink ? "Open this record on the source site" : "Open the source organisation's homepage"}
      >
        {link.org} <span aria-hidden="true">↗</span>
      </a>
    </p>
  );
}

export function ExternalLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-white/70 hover:text-white/90 text-xs transition-colors"
    >
      <svg aria-hidden="true" className="w-3 h-3 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
      </svg>
      {label}
    </a>
  );
}

export function ExternalLinks({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-2 pt-2 border-t border-white/5">
      {children}
    </div>
  );
}

