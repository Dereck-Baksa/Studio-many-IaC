#!/usr/bin/env bash
set -e

CODE_ARTIFACT_BUCKET="code-artifact-bucket-studio-essencia"

JOBS_DIR="$(cd "$(dirname "$0")" && pwd)/glue-jobs"
REGION="${AWS_REGION:-us-east-1}"
FUNCTION="${LAMBDA_FUNCTION_NAME:-${PROJECT_NAME:-data-lake-no-show}-ingestao}"
SQL_FUNCTION="${SQL_LAMBDA_FUNCTION_NAME:-data-lake-sql-ingestao}"
NO_SHOW_ZIP="$(mktemp --suffix=.zip)"
SQL_ZIP="$(mktemp --suffix=.zip)"
SQL_PACKAGE_DIR="$(mktemp -d)"
trap 'rm -f "$NO_SHOW_ZIP" "$SQL_ZIP"; rm -rf "$SQL_PACKAGE_DIR"' EXIT

NO_SHOW_SOURCE="$(dirname "$0")/../aws-lambda-dados-no-show/lambda-py/lambda_function/lambda_function.py"
SQL_LAMBDA_DIR="$(dirname "$0")/../aws-lambda-dados-sql/lambda-py"
SQL_SOURCE="$SQL_LAMBDA_DIR/lambda_function/ingestao_sql_s3.py"

python -m pip install --disable-pip-version-check \
  --target "$SQL_PACKAGE_DIR" \
  -r "$SQL_LAMBDA_DIR/requirements.txt"
cp "$SQL_SOURCE" "$SQL_PACKAGE_DIR/ingestao_sql_s3.py"
python -c "import os, sys, zipfile; root, archive = sys.argv[1:]; z = zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED); [z.write(os.path.join(folder, name), os.path.relpath(os.path.join(folder, name), root)) for folder, _, names in os.walk(root) for name in names]; z.close()" \
  "$SQL_PACKAGE_DIR" "$SQL_ZIP"
python -c "import sys, zipfile; zipfile.ZipFile(sys.argv[2], 'w', zipfile.ZIP_DEFLATED).write(sys.argv[1], 'lambda_function.py')" \
  "$NO_SHOW_SOURCE" "$NO_SHOW_ZIP"

aws --region "$REGION" sts get-caller-identity
aws --region "$REGION" s3 cp "$JOBS_DIR/etl_unir_fontes.py" \
  "s3://$CODE_ARTIFACT_BUCKET/etl_unir_fontes.py"
aws --region "$REGION" s3 cp "$JOBS_DIR/etl_calculo_no_show.py" \
  "s3://$CODE_ARTIFACT_BUCKET/etl_calculo_no_show.py"
aws --region "$REGION" s3 cp "$JOBS_DIR/etl_dashboard_silver.py" \
  "s3://$CODE_ARTIFACT_BUCKET/etl_dashboard_silver.py"
aws --region "$REGION" s3 cp "$JOBS_DIR/etl_dashboard_gold.py" \
  "s3://$CODE_ARTIFACT_BUCKET/etl_dashboard_gold.py"
aws --region "$REGION" s3 cp \
  "$(dirname "$0")/dashboard-data.schema.json" \
  "s3://$CODE_ARTIFACT_BUCKET/dashboard-data.schema.json"
aws --region "$REGION" s3 cp \
  "$SQL_SOURCE" \
  "s3://$CODE_ARTIFACT_BUCKET/sql/ingestao_sql_s3.py"

aws --region "$REGION" s3 cp "$NO_SHOW_ZIP" \
  "s3://$CODE_ARTIFACT_BUCKET/lambda/no-show/lambda_function.zip"
aws --region "$REGION" s3 cp "$SQL_ZIP" \
  "s3://$CODE_ARTIFACT_BUCKET/lambda/sql/ingestao_sql_s3.zip"

publish_lambda() {
  local function_name="$1"
  local artifact_key="$2"
  if error="$(aws --region "$REGION" lambda get-function \
    --function-name "$function_name" 2>&1)"; then
    aws --region "$REGION" lambda update-function-code \
      --function-name "$function_name" \
      --s3-bucket "$CODE_ARTIFACT_BUCKET" \
      --s3-key "$artifact_key" \
      --publish
  elif [[ "$error" == *"ResourceNotFoundException"* ]]; then
    echo "Pacote enviado. Crie a Lambda $function_name com Terraform e rode o script novamente."
  else
    echo "$error" >&2
    return 1
  fi
}

if publish_lambda "$FUNCTION" "lambda/no-show/lambda_function.zip"; then
  publish_lambda "$SQL_FUNCTION" "lambda/sql/ingestao_sql_s3.zip"
else
  exit 1
fi
