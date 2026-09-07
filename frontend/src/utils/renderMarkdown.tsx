// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Fragment, ReactNode } from "react";

/**
 * Minimal markdown-to-React renderer for blog articles.
 * Supports: ## headings, **bold**, *italic*, - bullet lists, blank-line paragraphs.
 * Returns React elements with no external dependencies.
 */

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={i}>{part.slice(1, -1)}</em>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

type Block =
  | { type: "h2" | "h3"; text: string }
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] };

function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("### ")) {
      blocks.push({ type: "h3", text: line.slice(4).trim() });
      i++;
      continue;
    }

    if (line.startsWith("## ")) {
      blocks.push({ type: "h2", text: line.slice(3).trim() });
      i++;
      continue;
    }

    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) {
        items.push(lines[i].slice(2).trim());
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (line.trim() === "") {
      i++;
      continue;
    }

    const textLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].startsWith("## ") &&
      !lines[i].startsWith("### ") &&
      !lines[i].startsWith("- ")
    ) {
      textLines.push(lines[i]);
      i++;
    }
    if (textLines.length > 0) {
      blocks.push({ type: "p", text: textLines.join(" ") });
    }
  }

  return blocks;
}

interface Props {
  markdown: string;
  className?: string;
}

export function MarkdownRenderer({ markdown, className }: Props) {
  const blocks = parseBlocks(markdown);

  return (
    <div className={className}>
      {blocks.map((block, idx) => {
        if (block.type === "h2") {
          return (
            <h2 key={idx} className="text-lg font-semibold text-white mt-8 mb-3">
              {block.text}
            </h2>
          );
        }
        if (block.type === "h3") {
          return (
            <h3 key={idx} className="text-base font-semibold text-white/95 mt-6 mb-2">
              {block.text}
            </h3>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={idx} className="list-disc list-inside space-y-1 my-3">
              {block.items.map((item, j) => (
                <li key={j} className="text-white/85 text-sm leading-relaxed">
                  {renderInline(item)}
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={idx} className="text-white/85 text-sm leading-relaxed mb-4">
            {renderInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
