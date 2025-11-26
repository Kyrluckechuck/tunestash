# Optimized frontend Dockerfile with smaller production image
ARG VITE_API_URL

# =============================================================================
# Stage 1: Base Node setup (cached unless Node version changes)
# =============================================================================
FROM node:20-alpine AS node-base
WORKDIR /app
RUN apk add --no-cache yarn

# =============================================================================
# Stage 2: Dependencies (cached unless package files change)
# =============================================================================
FROM node-base AS deps
COPY package.json yarn.lock ./
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}

# Use cache mount for yarn with retry logic for CI reliability
# Increased network timeout for slow ARM64 QEMU builds
RUN --mount=type=cache,target=/usr/local/share/.cache/yarn,id=yarn-cache,sharing=locked \
    yarn config set network-timeout 600000 && \
    yarn install --frozen-lockfile || \
    (echo "Retry 1/3..." && sleep 5 && yarn install --frozen-lockfile) || \
    (echo "Retry 2/3..." && sleep 10 && yarn install --frozen-lockfile) || \
    (echo "Retry 3/3..." && sleep 15 && yarn install --frozen-lockfile)

# =============================================================================
# Stage 3: Source code (rebuilds when source changes)
# =============================================================================
FROM deps AS source
COPY . .

# =============================================================================
# Stage 4: Development (for local dev - no build step)
# =============================================================================
FROM source AS development
# Don't run build - dev server serves files directly from source

# =============================================================================
# Stage 5: Test (for CI/CD)
# =============================================================================
FROM source AS test
RUN yarn test:run

# =============================================================================
# Stage 6: Build (for production)
# =============================================================================
FROM source AS build
RUN yarn build

# =============================================================================
# Stage 7: Production (nginx serving static files)
# =============================================================================
FROM nginx:alpine AS production

# Use a minimal nginx config
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Add wget for healthcheck (minimal addition)
RUN apk add --no-cache wget

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

# Default target
FROM production
