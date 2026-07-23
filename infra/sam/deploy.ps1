# Deploy Migration Oracle SAM stack (Windows).
# Works around missing cloudformation:DescribeStackEvents by executing the
# changeset manually, then wiring stack outputs into repo-root .env.
#
# Usage:
#   cd infra\sam
#   .\deploy.ps1

param(
  [string]$StackName = "migration-oracle",
  [string]$Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$SamDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $SamDir "..\..")
$EnvFile = Join-Path $RepoRoot ".env"

function Import-DotEnv([string]$Path) {
  Get-Content $Path | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $k, $v = $_.Split('=', 2)
    Set-Item -Path "Env:$k" -Value $v
  }
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
  # AWS CLI --output text can include trailing CR/LF/whitespace.
  $Value = ($Value -replace '[\r\n]+', '').Trim()
  if (-not $Value -or $Value -eq "None") {
    throw "Refusing to write empty $Key into .env"
  }
  $raw = Get-Content -Path $Path -Raw
  if ($null -eq $raw) { $raw = "" }
  # Strip UTF-8 BOM so ^Key= matches after prior Set-Content -Encoding utf8.
  if ($raw.Length -gt 0 -and [int][char]$raw[0] -eq 0xFEFF) {
    $raw = $raw.Substring(1)
  }
  $lines = $raw -split "`r?`n", -1
  $found = $false
  $out = foreach ($line in $lines) {
    if ($line -match "^$([regex]::Escape($Key))=") {
      $found = $true
      "$Key=$Value"
    } else {
      $line
    }
  }
  if (-not $found) { $out += "$Key=$Value" }
  # utf8NoBOM keeps keys matchable on subsequent updates (PS 6+ / .NET).
  $text = ($out -join "`n").TrimEnd() + "`n"
  [System.IO.File]::WriteAllText($Path, $text)
}

Import-DotEnv $EnvFile
if (-not $env:BEDROCK_PREDICTION_MODEL_ID) {
  $env:BEDROCK_PREDICTION_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
}
if (-not $env:DATABASE_URL) { throw "DATABASE_URL missing in .env" }
if (-not $env:CCLOUD_API_SECRET) { throw "CCLOUD_API_SECRET missing in .env" }

Set-Location $SamDir
if (-not (Test-Path ".aws-sam\build\template.yaml")) {
  Write-Host "No build artifacts - running build.ps1 first"
  & (Join-Path $SamDir "build.ps1")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "sam deploy --stack-name $StackName ..."
sam deploy `
  --stack-name $StackName `
  --region $Region `
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
  --resolve-s3 `
  --no-confirm-changeset `
  --disable-rollback `
  --parameter-overrides `
    "ProjectName=migration-oracle" `
    "EnvironmentName=demo" `
    "DatabaseUrl=$env:DATABASE_URL" `
    "CCloudApiSecret=$env:CCLOUD_API_SECRET" `
    "CCloudApiKey=$env:CCLOUD_API_KEY" `
    "CCloudApiKeySecretArn=$env:CCLOUD_API_KEY_SECRET_ARN" `
    "BedrockPredictionModelId=$env:BEDROCK_PREDICTION_MODEL_ID" `
    "BedrockEmbeddingModelId=amazon.titan-embed-text-v2:0"

$status = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
  --query 'Stacks[0].StackStatus' --output text 2>$null
Write-Host "Stack status: $status"

if ($status -match 'REVIEW_IN_PROGRESS') {
  $cs = aws cloudformation list-change-sets --stack-name $StackName --region $Region `
    --query 'Summaries[?ExecutionStatus==`AVAILABLE`] | [0].ChangeSetId' --output text
  if (-not $cs -or $cs -eq "None") { throw "No AVAILABLE changeset to execute" }
  Write-Host "Executing changeset: $cs"
  aws cloudformation execute-change-set --change-set-name $cs --region $Region --disable-rollback
}

$deadline = (Get-Date).AddMinutes(20)
do {
  $status = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query 'Stacks[0].StackStatus' --output text
  Write-Host "$(Get-Date -Format HH:mm:ss) $status"
  if ($status -match 'COMPLETE|FAILED' -and $status -notmatch 'IN_PROGRESS|REVIEW') { break }
  Start-Sleep -Seconds 20
} while ((Get-Date) -lt $deadline)

if ($status -ne "CREATE_COMPLETE" -and $status -ne "UPDATE_COMPLETE") {
  Write-Host "Deploy did not succeed. Failed resources:"
  aws cloudformation describe-stack-resources --stack-name $StackName --region $Region `
    --query 'StackResources[?ResourceStatus!=`CREATE_COMPLETE`].[LogicalResourceId,ResourceStatus,ResourceStatusReason]' `
    --output table
  exit 1
}

$workflow = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
  --query 'Stacks[0].Outputs[?OutputKey==`MigrationWorkflowArn`].OutputValue' --output text
$bucket = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
  --query 'Stacks[0].Outputs[?OutputKey==`ArtifactsBucket`].OutputValue' --output text

if (-not $workflow -or $workflow -eq "None") { throw "MigrationWorkflowArn output missing" }
if (-not $bucket -or $bucket -eq "None") { throw "ArtifactsBucket output missing" }

Set-DotEnvValue $EnvFile "MIGRATION_WORKFLOW_ARN" $workflow
Set-DotEnvValue $EnvFile "RUN_ARTIFACTS_BUCKET" $bucket
Set-DotEnvValue $EnvFile "AWS_ENABLED" "true"
Set-DotEnvValue $EnvFile "AWS_DEFAULT_REGION" $Region
Set-DotEnvValue $EnvFile "BEDROCK_EMBEDDING_MODEL_ID" "amazon.titan-embed-text-v2:0"

Write-Host ""
Write-Host "Deploy complete."
Write-Host "  MIGRATION_WORKFLOW_ARN=$workflow"
Write-Host "  RUN_ARTIFACTS_BUCKET=$bucket"
Write-Host 'Restart API with: .\dev.ps1'
