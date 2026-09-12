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

# VITE_API_BASE_URL=/api so the SPA calls /api/* which server.js proxies
ENV VITE_API_BASE_URL=/api
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

