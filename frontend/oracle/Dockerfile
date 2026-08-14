# Migration Oracle web console (Next.js 16, Turborepo monorepo).
# Build context is frontend/oracle (the monorepo root), NOT the repo root.
#
#   docker build -f frontend/oracle/Dockerfile frontend/oracle \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example \
#     --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_... \
#     -t migration-oracle-web

# ---- deps: install once against the lockfile, cached unless a manifest moves
FROM node:22-alpine AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/
COPY packages/eslint-config/package.json packages/eslint-config/
COPY packages/typescript-config/package.json packages/typescript-config/
RUN npm ci

# ---- builder
FROM node:22-alpine AS builder
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY . .

# NEXT_PUBLIC_* are inlined into the client bundle at build time, not read at
# container start. Passing the API URL as a runtime env var has no effect: the
# bundle would keep client.ts's DEFAULT_API_BASE_URL (http://127.0.0.1:8000) and
# every visitor's browser would call their own machine over plain HTTP.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build --workspace=web

# ---- runner: standalone output only
FROM node:22-alpine AS runner
WORKDIR /repo

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# standalone/ carries its own minimal node_modules and the monorepo directory
# shape (apps/web/server.js). static/ is deliberately not bundled into it.
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "apps/web/server.js"]
