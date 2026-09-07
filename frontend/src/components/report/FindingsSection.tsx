// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { Finding } from "../ImpactReport";

interface Props {
  findings: Finding[];
}

const severityStyle: Record<Finding["severity"], string> = {
  Critical: "border-red-500/30 bg-red-500/5",
  High: "border-orange-500/30 bg-orange-500/5",
  Moderate: "border-yellow-500/30 bg-yellow-500/5",
  Low: "border-green-500/30 bg-green-500/5",
};

const severityBadge: Record<Finding["severity"], string> = {
  Critical: "bg-red-500/20 text-red-400 border-red-500/30",
  High: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  Moderate: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  Low: "bg-green-500/20 text-green-400 border-green-500/30",
};

export function FindingsSection({ findings }: Props) {
  return (
    <section className="mb-8">
      <h2 className="text-[13px] font-semibold text-white/90 mb-4 print:text-gray-900">
        5. Numbered Findings
      </h2>

      {findings.length === 0 ? (
        <p className="text-[13px] text-white/65 italic print:text-gray-500">
          No environmental findings to report.
        </p>
      ) : (
        <div className="space-y-3">
          {findings.map(f => (
            <div
              key={f.number}
              className={`border rounded-lg p-4 ${severityStyle[f.severity]} print:bg-white print:border-gray-300`}
            >
              {/* Header: number + severity badge + type */}
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[13px] font-semibold text-white/90 print:text-gray-900">
                  #{f.number}
                </span>
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-medium border ${severityBadge[f.severity]} print:bg-white print:border-gray-300 print:text-gray-700`}
                >
                  {f.severity}
                </span>
                <span className="text-xs text-white/70 print:text-gray-500">
                  {f.type}
                </span>
              </div>

              {/* Observation */}
              <p className="text-[13px] text-white/85 leading-relaxed mb-1 print:text-gray-700">
                {f.observation}
              </p>

              {/* Spatial link */}
              {f.spatial_link && (
                <p className="text-xs text-white/70 leading-relaxed mb-1 print:text-gray-500">
                  {f.spatial_link}
                </p>
              )}

              {/* Environmental context */}
              {f.environmental_context && (
                <p className="text-xs text-white/70 leading-relaxed mb-1 print:text-gray-500">
                  {f.environmental_context}
                </p>
              )}

              {/* Footer ref line */}
              <p className="text-xs text-white/60 mt-2 print:text-gray-400">
                Ref: Profile {f.refs.profile_id.slice(-8)} |{" "}
                <a
                  href={`#claim-${f.refs.claim_id}`}
                  className="text-white/70 hover:text-white/90 print:text-blue-600"
                >
                  Claim {f.refs.claim_id}
                </a>
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
