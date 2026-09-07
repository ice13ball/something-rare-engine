// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export type ProgressCallback = (received: number, total: number) => void;

/**
 * Fetch JSON with byte-level progress tracking via ReadableStream.
 * Falls back to standard fetch if Content-Length is missing or body is not streamable.
 * Retries up to `maxRetries` times with exponential backoff on failure.
 */
export async function fetchWithProgress(
  url: string,
  onProgress: ProgressCallback,
  maxRetries = 2,
): Promise<any> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) {
      // Exponential backoff: 2s, 4s
      await new Promise(r => setTimeout(r, 2000 * attempt));
      onProgress(0, 0); // Reset progress bar for retry
    }

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(response.statusText);

      const contentLength = response.headers.get("Content-Length");
      const total = contentLength ? parseInt(contentLength, 10) : 0;

      // Fallback: no Content-Length or no ReadableStream support
      if (!total || !response.body) {
        onProgress(0, 0);
        const data = await response.json();
        const size = new Blob([JSON.stringify(data)]).size;
        onProgress(size, size);
        return data;
      }

      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let received = 0;

      onProgress(0, total);

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        onProgress(received, total);
      }

      const body = new Uint8Array(received);
      let offset = 0;
      for (const chunk of chunks) {
        body.set(chunk, offset);
        offset += chunk.length;
      }

      return JSON.parse(new TextDecoder().decode(body));
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (attempt < maxRetries) {
        console.warn(`[fetch] Retry ${attempt + 1}/${maxRetries} for ${url}: ${lastError.message}`);
      }
    }
  }

  throw lastError!;
}
