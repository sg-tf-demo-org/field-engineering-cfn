package main

import rego.v1

# Mandatory-tags gate.
# Every taggable resource must carry the org-required tag keys.
# Environment values must be from an approved enumerated set.
# Fail-closed.

required_tags := {"Owner", "CostCenter", "Environment"}

allowed_environments := {"dev", "staging", "prod"}

taggable := {
	"AWS::S3::Bucket",
	"AWS::SQS::Queue",
	"AWS::SNS::Topic",
	"AWS::Lambda::Function",
	"AWS::DynamoDB::Table",
	"AWS::EC2::Instance",
	"AWS::EC2::SecurityGroup",
	"AWS::EC2::VPC",
	"AWS::IAM::Role",
	"AWS::KMS::Key",
	"AWS::RDS::DBInstance",
}

tag_keys(res) := {k | some t in res.Properties.Tags; k := t.Key}

tag_value(res, key) := v if {
	some t in res.Properties.Tags
	t.Key == key
	v := t.Value
}

deny contains msg if {
	some name, res in input.Resources
	taggable[res.Type]
	provided := tag_keys(res)
	missing := required_tags - provided
	count(missing) > 0
	msg := sprintf("MANDATORY-TAGS: resource '%s' (%s) is missing required tags: %v", [name, res.Type, missing])
}

deny contains msg if {
	some name, res in input.Resources
	taggable[res.Type]
	not res.Properties.Tags
	msg := sprintf("MANDATORY-TAGS: resource '%s' (%s) has no Tags block; required: %v", [name, res.Type, required_tags])
}

# Enumerated Environment values only (no free-text).
deny contains msg if {
	some name, res in input.Resources
	taggable[res.Type]
	env := tag_value(res, "Environment")
	not allowed_environments[env]
	msg := sprintf("MANDATORY-TAGS: resource '%s' has Environment='%s' — allowed: %v", [name, env, allowed_environments])
}
