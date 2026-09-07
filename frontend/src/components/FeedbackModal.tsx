// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

type Kind = "positive" | "bug" | "suggestion" | "api_key";
type State = "idle" | "sending" | "done" | "error";

const KINDS: { id: Kind; emoji: string; label: string }[] = [
  { id: "positive",   emoji: "✅", label: "Working well" },
  { id: "bug",        emoji: "🐛", label: "Something's broken" },
  { id: "suggestion", emoji: "💡", label: "Suggestion" },
  { id: "api_key",    emoji: "🔑", label: "Request API key" },
];

export function FeedbackModal({ onClose, initialKind = "suggestion" }: { onClose: () => void; initialKind?: Kind }) {
  const [kind, setKind]       = useState<Kind>(initialKind);
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [state, setState]     = useState<State>("idle");
  const textareaRef           = useRef<HTMLTextAreaElement>(null);
  const modalOpenedAt         = useRef(Date.now());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  async function submit() {
    if (!message.trim()) return;
    setState("sending");
    try {
      const res = await fetch(`${API}/api/v1/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
        body: JSON.stringify({
          kind,
          message: message.trim(),
          contact: contact.trim() || null,
          page_url: window.location.href,
          website,
          dwell_ms: Date.now() - modalOpenedAt.current,
        }),
      });
      setState(res.ok ? "done" : "error");
    } catch {
      setState("error");
    }
  }

  return (
    <div
      className="fixed inset-0 z-overlay flex items-center justify-center p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <button
        className="absolute inset-0 bg-surface-overlay cursor-default"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="relative bg-[#0d1117] border border-white/10 rounded-xl shadow-2xl w-full max-w-lg flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10 flex-shrink-0">
          <span className="text-white/90 text-xs font-semibold uppercase tracking-wider">
            Tell me what you think
          </span>
          <button
            onClick={onClose}
            className="text-white/60 hover:text-white text-xl leading-none ml-4"
            aria-label="Close"
          >×</button>
        </div>

        {/* Content */}
        <div className="p-5 space-y-4">
          {state === "done" ? (
            <div className="text-center py-6 space-y-3">
              <p className="text-2xl">🙏</p>
              <p className="text-white/90 text-sm font-medium">Thanks — got it.</p>
              <p className="text-white/70 text-xs leading-relaxed">
                I read every one. If you left an email, I'll get back to you.
              </p>
              <button
                onClick={onClose}
                className="mt-2 px-4 py-1.5 rounded bg-white/10 hover:bg-white/15 text-white/85 text-xs transition-colors"
              >
                Close
              </button>
            </div>
          ) : (
            <>
              <p className="text-white/70 text-xs leading-relaxed">
                This is a one-person project. Whether something's broken, something works
                really well, or you have an idea I haven't thought of — I genuinely want to hear it.
              </p>

              {/* Kind selector */}
              <div className="flex gap-2">
                {KINDS.map(k => (
                  <button
                    key={k.id}
                    onClick={() => setKind(k.id)}
                    className={`flex-1 flex flex-col items-center gap-1 py-2 px-1 rounded-lg border text-xs transition-colors ${
                      kind === k.id
                        ? "border-white/30 bg-white/8 text-white/90"
                        : "border-white/10 text-white/60 hover:border-white/20 hover:text-white/75"
                    }`}
                  >
                    <span className="text-base leading-none">{k.emoji}</span>
                    <span className="leading-tight text-center">{k.label}</span>
                  </button>
                ))}
              </div>

              {/* Message */}
              <textarea
                ref={textareaRef}
                value={message}
                onChange={e => setMessage(e.target.value)}
                maxLength={4000}
                rows={4}
                placeholder={kind === "api_key"
                  ? "Tell me a bit about your use case (institution, what data, roughly how often) and I'll set you up with a key."
                  : "What happened, what you expected, or what you'd like to see…"}
                className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white/90 placeholder-white/20 resize-none focus:outline-none focus:border-white/25 transition-colors"
              />

              {/* Contact */}
              <div>
                <label className="text-white/60 text-[10px] font-mono uppercase tracking-wider block mb-1">
                  Email — optional, only if you want a reply
                </label>
                <input
                  type="text"
                  value={contact}
                  onChange={e => setContact(e.target.value)}
                  maxLength={200}
                  placeholder="you@example.com or leave blank"
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white/90 placeholder-white/20 focus:outline-none focus:border-white/25 transition-colors"
                />
              </div>

              {/* Honeypot — visually hidden */}
              <input
                type="text"
                value={website}
                onChange={e => setWebsite(e.target.value)}
                tabIndex={-1}
                aria-hidden="true"
                style={{ display: "none" }}
                autoComplete="off"
              />

              {state === "error" && (
                <p className="text-red-400/70 text-xs">Something went wrong — please try again.</p>
              )}

              <button
                onClick={submit}
                disabled={state === "sending" || !message.trim()}
                className="w-full py-2 rounded-lg bg-white/10 hover:bg-white/15 disabled:opacity-40 disabled:cursor-not-allowed text-white/90 text-xs font-medium transition-colors"
              >
                {state === "sending" ? "Sending…" : "Send"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
