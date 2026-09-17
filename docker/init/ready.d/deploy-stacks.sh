#!/usr/bin/env bash
# Deploy dos scripts CloudFormation no LocalStack (executado quando o LocalStack estiver pronto)
set -euo pipefail

deploy() {
  local name=$1
  local file=$2
  shift 2
  echo "=== Deploying ${name} (${file}) ==="
  awslocal cloudformation deploy --stack-name "${name}" --template-file "${file}" "$@"
  echo "=== OK: ${name} ==="
}

deploy studio-many-network /opt/scripts/network.yml
deploy studio-many-ec2 /opt/scripts/ec2.yml --parameter-overrides RootVolumeType=gp2 RootVolumeEncrypted=false
deploy studio-many-rds /opt/scripts/rds.yml --parameter-overrides MasterUserPassword=LocalStack123 StorageEncrypted=false DeletionProtection=false MultiAZ=false
deploy studio-many-efs /opt/scripts/efs.yml --parameter-overrides Encrypted=false
deploy studio-many-alb /opt/scripts/alb.yml


cp /opt/scripts/cloudwatch-alarm.yml /tmp/cloudwatch-alarm.yml
sed -i '/^      Dimensions:/d' /tmp/cloudwatch-alarm.yml
deploy studio-many-cloudwatch /tmp/cloudwatch-alarm.yml

awslocal cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[].StackName" --output text