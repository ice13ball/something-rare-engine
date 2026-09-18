# ── Stage 1: Build ───────────────────────────────────────────────────────────
# --platform=$BUILDPLATFORM pins this stage to the machine doing the building,
# NOT to the image's target platform. On the Pi 5 runner that means npm/vite run
# natively on arm64 instead of under qemu; the runtime stage below stays amd64
# for Cloud Run. Safe only because stage 2 has no RUN — it copies and nothing
# else — and because every production dependency is pure JavaScript. ⛔ A native
# module in `dependencies` would break this: it would be compiled for arm64 and
# copied into an amd64 image. Check before adding one.
FROM --platform=$BUILDPLATFORM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# ⛔ Deliberately UNSET. Every call site across src/ already hardcodes the
# literal "/api" prefix itself (`${API}/api/v1/...` — grep confirms 100+ of
# them, e.g. SeoPage.tsx, VentReport.tsx, useTemporalCoverage.ts, Map3D.tsx,
# every panel). Setting VITE_API_BASE_URL=/api here — as this line used to —
# baked a SECOND "/api" onto every one of those requests, producing
# /api/api/v1/... in production only (dev never showed it: vite.config.ts's
# proxy needs no VITE_API_BASE_URL at all). Both layers of the BFF proxy
# happen to strip a leading /api twice (Express's own mount-prefix strip on
# `app.use('/api', …)`, then http-proxy-middleware's pathRewrite matching
# AGAIN on what Express left behind) so the request still reached the right
# backend route — which is exactly why this went unnoticed until Googlebot's
# crawl surfaced the literal doubled URL and its extra proxy hop timed out as
# a 504 during a slow backend (2026-09-18 incident). Leaving this unset makes
# `import.meta.env.VITE_API_BASE_URL ?? ""` resolve to "", matching dev.
RUN npm run build

# Prune devDependencies so the runtime stage gets a lean node_modules
RUN npm prune --omit=dev

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM node:22-alpine AS runtime

WORKDIR /app

COPY package.json ./
COPY server.js ./
COPY seo/ ./seo/
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

# Cloud Run injects PORT automatically
ENV NODE_ENV=production

CMD ["node", "server.js"]

