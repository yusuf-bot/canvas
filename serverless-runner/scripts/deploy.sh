#!/bin/bash

set -e

ENVIRONMENT=${1:-staging}
NAMESPACE="serverless-runner"

if [ "$ENVIRONMENT" = "staging" ]; then
    NAMESPACE="serverless-runner-staging"
fi

echo "Deploying to $ENVIRONMENT environment (namespace: $NAMESPACE)"

# Create namespace if it doesn't exist
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Apply all Kubernetes manifests
echo "Applying Kubernetes manifests..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/backend/ -n $NAMESPACE
kubectl apply -f k8s/frontend/ -n $NAMESPACE

# Wait for deployments to be ready
echo "Waiting for deployments to be ready..."
kubectl wait --for=condition=available --timeout=300s deployment/backend-deployment -n $NAMESPACE
kubectl wait --for=condition=available --timeout=300s deployment/frontend-deployment -n $NAMESPACE

echo "✅ Deployment to $ENVIRONMENT completed successfully!"