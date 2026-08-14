FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked in at build time — Next.js inlines NEXT_PUBLIC_* into the client
# bundle, so it has to be present now, not just at container start.
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
# Also build-time, not just runtime: next.config.mjs's rewrites() runs once
# during `next build` to produce the routes manifest, not again at server
# start — an env var set only on the running container arrives too late.
ARG MUSE_API_INTERNAL_URL
ENV MUSE_API_INTERNAL_URL=$MUSE_API_INTERNAL_URL
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
