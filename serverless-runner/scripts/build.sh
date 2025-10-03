#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting build process...${NC}"

# Get git commit hash
GIT_COMMIT=$(git rev-parse --short HEAD)
IMAGE_TAG="${GIT_COMMIT}-$(date +%s)"

echo -e "${YELLOW}Building images with tag: ${IMAGE_TAG}${NC}"

# Build backend
echo -e "${YELLOW}Building backend...${NC}"
cd backend
docker build -t backend:${IMAGE_TAG} .
docker tag backend:${IMAGE_TAG} backend:latest
cd ..

# Build frontend
echo -e "${YELLOW}Building frontend...${NC}"
cd frontend
docker build -t frontend:${IMAGE_TAG} .
docker tag frontend:${IMAGE_TAG} frontend:latest
cd ..

echo -e "${GREEN}✅ Build completed successfully!${NC}"
echo -e "${GREEN}Backend image: backend:${IMAGE_TAG}${NC}"
echo -e "${GREEN}Frontend image: frontend:${IMAGE_TAG}${NC}"