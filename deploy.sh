#!/bin/bash
set -euo pipefail

# ============================================================================
# Intel Sweep — Deploy
# Unified deployment entry point. Detects or accepts target platform.
#
# Usage:
#   ./scripts/deploy.sh              # auto-detect from environment
#   ./scripts/deploy.sh gcp          # explicit target
#   ./scripts/deploy.sh aws
#   ./scripts/deploy.sh azure
#   ./scripts/deploy.sh docker       # docker-compose on any host
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-auto}"

_detect_platform() {
  if [ -n "${GCP_PROJECT_ID:-}" ] || command -v gcloud &>/dev/null && gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q .; then
    echo "gcp"
  elif [ -n "${AWS_ACCOUNT_ID:-}" ] || command -v aws &>/dev/null && aws sts get-caller-identity &>/dev/null 2>&1; then
    echo "aws"
  elif command -v az &>/dev/null && az account show &>/dev/null 2>&1; then
    echo "azure"
  elif command -v docker &>/dev/null; then
    echo "docker"
  else
    echo "unknown"
  fi
}

if [ "${TARGET}" = "auto" ]; then
  TARGET=$(_detect_platform)
  echo "Auto-detected platform: ${TARGET}"
fi

case "${TARGET}" in
  gcp)
    echo "Deploying to Google Cloud (Cloud Run + Cloud Scheduler)..."
    bash "${SCRIPT_DIR}/deploy-gcp.sh"
    ;;
  aws)
    echo "Deploying to AWS (ECS Fargate + EventBridge)..."
    bash "${SCRIPT_DIR}/deploy-aws.sh"
    ;;
  azure)
    echo "Deploying to Azure (Container Apps + Timer Trigger)..."
    bash "${SCRIPT_DIR}/deploy-azure.sh"
    ;;
  docker)
    echo "Deploying with Docker Compose..."
    cd "${SCRIPT_DIR}/.."
    if [ ! -f config.yaml ]; then
      echo "ERROR: config.yaml not found. Copy config.example.yaml and customize."
      exit 1
    fi
    if [ ! -f .env ]; then
      echo "ERROR: .env file not found. Create one with your API keys."
      echo "  cp .env.example .env && nano .env"
      exit 1
    fi
    docker compose up -d --build
    echo ""
    echo "=== Docker deployment complete ==="
    echo "Logs:  docker compose logs -f"
    echo "Stop:  docker compose down"
    ;;
  *)
    echo "ERROR: Could not detect cloud platform."
    echo ""
    echo "Usage: ./scripts/deploy.sh [gcp|aws|azure|docker]"
    echo ""
    echo "Or set one of these environment variables:"
    echo "  GCP_PROJECT_ID   — for Google Cloud"
    echo "  AWS_REGION       — for AWS"
    echo "  AZURE_LOCATION   — for Azure"
    exit 1
    ;;
esac
