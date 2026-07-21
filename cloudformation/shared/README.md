# Shared conventions

- Required tags on every taggable resource: Owner, Environment, ManagedBy=aiden, CostCenter, AppStack
- Allowed region for demos: us-east-1 (Governance_Configuration)
- Environment values: dev | stage | uat | prod via Parameters.Environment
- Do not duplicate templates per env — use `params/<env>.json`
