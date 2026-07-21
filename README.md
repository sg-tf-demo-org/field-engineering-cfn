# aiden-aws-cloudformation

Governed AWS CloudFormation appstacks for Aiden demos.

## Exact file paths (never list directories)

`mcp-gitlab_get_file_contents` only works on **files**. Use:

| App | file_path |
|-----|-----------|
| checkout | `cloudformation/appstacks/checkout/template.yaml` |
| cart | `cloudformation/appstacks/cart/template.yaml` |
| payment | `cloudformation/appstacks/payment/template.yaml` |
| shipping | `cloudformation/appstacks/shipping/template.yaml` |
| currency | `cloudformation/appstacks/currency/template.yaml` |
| frontend | `cloudformation/appstacks/frontend/template.yaml` |
| product-catalog | `cloudformation/appstacks/product-catalog/template.yaml` |
| recommendation | `cloudformation/appstacks/recommendation/template.yaml` |
| demo-assets | `cloudformation/appstacks/demo-assets/template.yaml` |

Params: `cloudformation/appstacks/<app>/params/{dev,stage,uat,prod}.json`

Stack name: `aiden-<app>-<env>` (e.g. `aiden-checkout-dev`).

Do **not** call get_file_contents on `.`, `cloudformation/`, or `cloudformation/appstacks/`.
