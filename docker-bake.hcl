# Docker Bake file for parallel multi-platform builds
# Usage: docker buildx bake [target]
#   docker buildx bake --push              # Build and push all images
#   docker buildx bake backend             # Build only backend
#   docker buildx bake frontend            # Build only frontend
#
# Caching Strategy:
#   Both targets use dual-layer caching for optimal CI performance:
#   1. GitHub Actions cache (type=gha) - Fast in-runner cache, 10GB limit
#   2. Registry cache (type=registry) - Persistent cache stored in GHCR, no size limits
#   This significantly speeds up builds by caching yarn/pip package installations

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
    "type=gha,scope=backend-app",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash:buildcache"
  ]

  cache-to = [
    "type=gha,scope=backend-app,mode=max",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash:buildcache,mode=max"
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
    "type=gha,scope=frontend-app",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash-frontend:buildcache"
  ]

  cache-to = [
    "type=gha,scope=frontend-app,mode=max",
    "type=registry,ref=${REGISTRY}/${REPO_OWNER}/tunestash-frontend:buildcache,mode=max"
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
target "backend-local" {
  inherits = ["backend"]
  platforms = ["linux/amd64"]
  tags = ["local-backend:latest"]
  output = ["type=docker"]
}

target "frontend-local" {
  inherits = ["frontend"]
  platforms = ["linux/amd64"]
  tags = ["local-frontend:latest"]
  output = ["type=docker"]
}

group "local" {
  targets = ["backend-local", "frontend-local"]
}
