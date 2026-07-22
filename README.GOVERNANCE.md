# Aiden governance (GitHub)

Migrated from GitLab. Human-first PR loop:

1. Push any commit on a PR
2. `pr-governance-scan` calls `mcp-cdk-governance.validate_cdk_governance` (scan CFN templates)
3. Commit status `aiden/governance` + Details → Aiden watch URL
4. Approve/merge when PASS; progressive deploy is separate

GitLab CI is disabled (`.gitlab-ci.yml.disabled`).

<!-- governance gate smoke 20260722T132111Z -->
