FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL
# Next inlines NEXT_PUBLIC_* at BUILD time, so it must be present here, not only at runtime.
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# 4GB cgroup in some environments: cap the heap or the build is OOM-killed.
ENV NODE_OPTIONS=--max-old-space-size=2048
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.ts ./next.config.ts
COPY --from=build /app/tsconfig.json ./tsconfig.json
COPY --from=build /app/app ./app
COPY --from=build /app/lib ./lib
# public/ holds the self-hosted woff2 fonts. Without this the app builds and serves, but every font
# request 404s and the page silently falls back to the browser default serif.
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start"]
