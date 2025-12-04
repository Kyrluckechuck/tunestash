# Docker Bake file for parallel multi-platform builds
# Usage: docker buildx bake [target]
#   docker buildx bake --push              # Build and push all images
#   docker buildx bake backend             # Build only backend
#   docker buildx bake frontend            # Build only frontend
#
# Caching Strategy:
#   Both targets use dual-layer caching for optimal CI performance:
#   1. GitHub Actions cache (type=gha) - Fast in-runner cache, 10GB limit, per-branch
#   2. Registry cache (type=registry) - Persistent cache stored in GHCR at :cache tag
#   Uses zstd compression for smaller cache uploads/downloads.
#   Both amd64 and arm64 layers are cached together.

# Variables that can be overridden
variable "REGISTRY" {
  default = "ghcr.io"
}

variable "REPO_OWNER" {
  default = ""
}

variable "SHA" {
  default = "dev"
}

variable "BRANCH" {
  default = "main"
}

variable "PLATFORMS" {
  default = "linux/amd64,linux/arm64"
}

# Default group - builds both backend and frontend in parallel
group "default" {
  targets = ["backend", "frontend"]
}

# Backend image target
target "backend" {
  context = "."
  dockerfile = "Dockerfile"
  target = "backend-prod"
  platforms = split(",", PLATFORMS)

  tags = [
    # Always tag with SHA for traceability
    "${REGISTRY}/${REPO_OWNER}/tunestash:sha-${SHA}",
    # Tag with branch name (main becomes latest)
    BRANCH == "main"
      ? "${REGISTRY}/${REPO_OWNER}/tunestash:latest"
      : "${REGISTRY}/${REPO_OWNER}/tunestash:${BRANCH}"
  ]

  cache-from = [
    "type=gha,scope=backend",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash:cache"
  ]

  cache-to = [
    "type=gha,scope=backend,mode=max",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash:cache,mode=max,compression=zstd"
  ]

  # Disable attestations to fix GHCR tag association issues
  # See: https://github.com/docker/buildx/issues/1509
  attest = []

  labels = {
    "org.opencontainers.image.source" = "https://github.com/${REPO_OWNER}/tunestash"
    "org.opencontainers.image.revision" = "${SHA}"
    "org.opencontainers.image.created" = timestamp()
  }
}

# Frontend image target
target "frontend" {
  context = "./frontend"
  dockerfile = "Dockerfile"
  target = "production"
  platforms = split(",", PLATFORMS)

  tags = [
    # Always tag with SHA for traceability
    "${REGISTRY}/${REPO_OWNER}/tunestash-frontend:sha-${SHA}",
    # Tag with branch name (main becomes latest)
    BRANCH == "main"
      ? "${REGISTRY}/${REPO_OWNER}/tunestash-frontend:latest"
      : "${REGISTRY}/${REPO_OWNER}/tunestash-frontend:${BRANCH}"
  ]

  cache-from = [
    "type=gha,scope=frontend",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash-frontend:cache"
  ]

  cache-to = [
    "type=gha,scope=frontend,mode=max",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash-frontend:cache,mode=max,compression=zstd"
  ]

  # Disable attestations to fix GHCR tag association issues
  # See: https://github.com/docker/buildx/issues/1509
  attest = []

  labels = {
    "org.opencontainers.image.source" = "https://github.com/${REPO_OWNER}/tunestash"
    "org.opencontainers.image.revision" = "${SHA}"
    "org.opencontainers.image.created" = timestamp()
  }
}

# Local testing targets (single platform, loadable)
# These are used in docker-test for integration testing
# IMPORTANT: cache-to is explicitly disabled to prevent overwriting
# the multi-platform cache from docker-build with single-platform data
target "backend-local" {
  inherits = ["backend"]
  platforms = ["linux/amd64"]
  tags = ["local-backend:latest"]
  output = ["type=docker"]
  # Disable cache export to prevent overwriting multi-platform cache
  cache-to = []
}

target "frontend-local" {
  inherits = ["frontend"]
  platforms = ["linux/amd64"]
  tags = ["local-frontend:latest"]
  output = ["type=docker"]
  # Disable cache export to prevent overwriting multi-platform cache
  cache-to = []
}

group "local" {
  targets = ["backend-local", "frontend-local"]
}
