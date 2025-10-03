#!/bin/bash

ENVIRONMENT=${1:-staging}
NAMESPACE="serverless-runner"

if [ "$ENVIRONMENT" = "staging" ]; then
    NAMESPACE="serverless-runner-staging"
fi

echo "Cleaning up $ENVIRONMENT environment (namespace: $NAMESPACE)"

# Delete all resources
kubectl delete namespace $NAMESPACE --ignore-not-found=true

# Clean up Docker images
docker image prune -f
docker container prune -f

echo "✅ Cleanup completed!"