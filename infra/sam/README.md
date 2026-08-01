# SAM package (`infra/sam`)

Authoritative deploy instructions: **[docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md)**.

```bash
cd infra/sam
sam build
sam deploy --guided --region us-east-1
```

This template declares:

- Artifacts S3 bucket
- Seven workflow Lambdas + sweeper (ZIP; `ccloud_api` REST for provision)
- Step Functions state machine with `DefinitionUri` → `../stepfunctions/migration_workflow.asl.json` and `DefinitionSubstitutions` for every Lambda ARN

Outputs: `MigrationWorkflowArn`, `ArtifactsBucket`, and per-function ARNs.
