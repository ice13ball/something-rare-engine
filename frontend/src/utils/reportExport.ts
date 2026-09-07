// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Lazy-loaded export helpers for Impact Evidence Reports.
 * html2canvas and jsPDF are imported dynamically to avoid bundling
 * them for users who never export.
 */

export async function exportPNG(element: HTMLElement, filename: string): Promise<void> {
  const html2canvas = (await import("html2canvas")).default;
  const canvas = await html2canvas(element, {
    backgroundColor: "#0a0e14",
    scale: 2,
    useCORS: true,
    logging: false,
  });
  const link = document.createElement("a");
  link.download = filename;
  link.href = canvas.toDataURL("image/png");
  link.click();
}

export async function exportPDF(element: HTMLElement, filename: string): Promise<void> {
  const html2canvas = (await import("html2canvas")).default;
  const { jsPDF } = await import("jspdf");

  const canvas = await html2canvas(element, {
    backgroundColor: "#0a0e14",
    scale: 2,
    useCORS: true,
    logging: false,
  });

  const imgData = canvas.toDataURL("image/png");
  const imgW = canvas.width;
  const imgH = canvas.height;

  const pdf = new jsPDF("portrait", "mm", "a4");
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const margin = 5;
  const usableW = pageW - margin * 2;
  const scale = usableW / imgW;
  const scaledH = imgH * scale;

  // Split across pages if content is taller than one page
  let yOffset = 0;
  let page = 0;
  while (yOffset < scaledH) {
    if (page > 0) pdf.addPage();
    pdf.addImage(imgData, "PNG", margin, -yOffset + margin, usableW, scaledH);
    yOffset += pageH - margin * 2;
    page++;
  }
  pdf.save(filename);
}

interface CsvRow {
  [key: string]: string | number | boolean | null | undefined;
}

export function exportCSV(rows: CsvRow[], filename: string): void {
  if (rows.length === 0) return;
  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map(r => headers.map(h => {
      const v = r[h];
      if (v == null) return "";
      let s = String(v);
      // Guard against CSV injection — prefix formula-starting chars
      if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
      if (s.includes(",") || s.includes('"') || s.includes("\n"))
        return `"${s.replace(/"/g, '""')}"`;
      return s;
    }).join(",")),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv" });
  const link = document.createElement("a");
  link.download = filename;
  link.href = URL.createObjectURL(blob);
  link.click();
  URL.revokeObjectURL(link.href);
}
