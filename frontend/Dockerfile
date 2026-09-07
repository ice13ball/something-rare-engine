# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

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

