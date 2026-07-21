# aiden-aws-cloudformation

Brownfield CloudFormation Git SoT for **Aiden for Infra**.

## Layout

```text
cloudformation/
  appstacks/<app>/template.yaml     # one template per appstack
  appstacks/<app>/params/{dev,stage,uat,prod}.json
  shared/                           # naming + tagging conventions
```

**Stack name:** `aiden-<app>-<env>` (e.g. `aiden-checkout-dev`).

Appstacks mirror OpenTelemetry Astronomy Shop services: frontend, cart, checkout, payment, product-catalog, shipping, recommendation, currency (+ demo-assets).

## Flow

1. Engineer declares an outcome in Aiden
2. Governance (KB + cfn-lint/cfn-guard) runs **before** MR
3. MR lands here with `## Governance` evidence in the description
4. GitLab CI validates; after approval/merge a manual job notifies Aiden
5. Aiden webhook automation deploys via `mcp-cfn-deploy`

Writing Terraform/CLI is optional toil — not the default path.
