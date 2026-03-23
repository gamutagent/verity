#!/bin/bash
set -euo pipefail

# ============================================================================
# Intel Sweep — AWS Deployment
# Deploys to ECS Fargate + EventBridge Scheduler + Secrets Manager
# ============================================================================

REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="intel-sweep"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${STACK_NAME}"

echo "=== Intel Sweep AWS Deployment ==="
echo "Account: ${ACCOUNT_ID}"
echo "Region:  ${REGION}"
echo ""

# --- 1. Create ECR repository ---
echo "Creating ECR repository..."
aws ecr describe-repositories --repository-names "${STACK_NAME}" --region "${REGION}" 2>/dev/null || \
aws ecr create-repository --repository-name "${STACK_NAME}" --region "${REGION}"

# --- 2. Store secrets ---
echo "Storing secrets..."
_store_secret() {
  local name=$1 value=$2
  aws secretsmanager create-secret \
    --name "intel-sweep/${name}" \
    --secret-string "${value}" \
    --region "${REGION}" 2>/dev/null || \
  aws secretsmanager update-secret \
    --secret-id "intel-sweep/${name}" \
    --secret-string "${value}" \
    --region "${REGION}"
}

[ -n "${SEARCH_API_KEY:-}" ]   && _store_secret "SEARCH_API_KEY" "${SEARCH_API_KEY}"
[ -n "${SCORING_API_KEY:-}" ]  && _store_secret "SCORING_API_KEY" "${SCORING_API_KEY}"
[ -n "${SLACK_WEBHOOK_URL:-}" ] && _store_secret "SLACK_WEBHOOK_URL" "${SLACK_WEBHOOK_URL}"

# --- 3. Build and push container ---
echo "Building and pushing container..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

docker build -t "${STACK_NAME}" .
docker tag "${STACK_NAME}:latest" "${ECR_REPO}:latest"
docker push "${ECR_REPO}:latest"

# --- 4. Create ECS cluster + task definition ---
echo "Setting up ECS..."
aws ecs create-cluster --cluster-name "${STACK_NAME}" --region "${REGION}" 2>/dev/null || true

# Create execution role if it doesn't exist
EXEC_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${STACK_NAME}-exec-role"
cat > /tmp/trust-policy.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
POLICY

aws iam create-role \
  --role-name "${STACK_NAME}-exec-role" \
  --assume-role-policy-document file:///tmp/trust-policy.json 2>/dev/null || true

aws iam attach-role-policy \
  --role-name "${STACK_NAME}-exec-role" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"

# Register task definition
cat > /tmp/task-def.json << TASKDEF
{
  "family": "${STACK_NAME}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "containerDefinitions": [{
    "name": "${STACK_NAME}",
    "image": "${ECR_REPO}:latest",
    "essential": true,
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/${STACK_NAME}",
        "awslogs-region": "${REGION}",
        "awslogs-stream-prefix": "ecs"
      }
    },
    "secrets": [
      {"name": "SEARCH_API_KEY", "valueFrom": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:intel-sweep/SEARCH_API_KEY"},
      {"name": "SCORING_API_KEY", "valueFrom": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:intel-sweep/SCORING_API_KEY"},
      {"name": "SLACK_WEBHOOK_URL", "valueFrom": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:intel-sweep/SLACK_WEBHOOK_URL"}
    ]
  }]
}
TASKDEF

aws ecs register-task-definition \
  --cli-input-json file:///tmp/task-def.json \
  --region "${REGION}"

# --- 5. Create EventBridge schedule ---
echo "Creating EventBridge schedules..."

# Create scheduler role
cat > /tmp/scheduler-trust.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "scheduler.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
POLICY

aws iam create-role \
  --role-name "${STACK_NAME}-scheduler-role" \
  --assume-role-policy-document file:///tmp/scheduler-trust.json 2>/dev/null || true

SCHEDULER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${STACK_NAME}-scheduler-role"

# Get default VPC subnet for Fargate
SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" \
  --query "Subnets[0].SubnetId" --output text --region "${REGION}")

# Daily competitors scan
aws scheduler create-schedule \
  --name "${STACK_NAME}-competitors" \
  --schedule-expression "cron(0 7 * * ? *)" \
  --flexible-time-window '{"Mode": "OFF"}' \
  --target "{
    \"Arn\": \"arn:aws:ecs:${REGION}:${ACCOUNT_ID}:cluster/${STACK_NAME}\",
    \"RoleArn\": \"${SCHEDULER_ROLE_ARN}\",
    \"EcsParameters\": {
      \"TaskDefinitionArn\": \"arn:aws:ecs:${REGION}:${ACCOUNT_ID}:task-definition/${STACK_NAME}\",
      \"LaunchType\": \"FARGATE\",
      \"NetworkConfiguration\": {
        \"AwsvpcConfiguration\": {\"Subnets\": [\"${SUBNET_ID}\"], \"AssignPublicIp\": \"ENABLED\"}
      }
    },
    \"Input\": \"{\\\"topics\\\": [\\\"competitors\\\", \\\"market_signals\\\"]}\"
  }" \
  --region "${REGION}" 2>/dev/null || echo "Schedule already exists, skipping..."

echo ""
echo "=== AWS Deployment complete ==="
echo "Cluster:   ${STACK_NAME}"
echo "Console:   https://${REGION}.console.aws.amazon.com/ecs/v2/clusters/${STACK_NAME}"
