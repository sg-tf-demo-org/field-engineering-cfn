package main

import rego.v1

# Governance CSPM (Rego). Primary CSPM in CI is also run via the config-scanning
# engine; these rules mirror the DEMO showcase policies so the gate is enforceable
# locally/offline and findings are consistent.
#
# Showcase policies enforced here (see docs/governance-demo-policy-set.md):
#   - No public object storage (ACL / incomplete PublicAccessBlock)
#   - Encryption at rest with customer-managed KMS (CMK) for S3
#   - No SSH/RDP from the public internet (0.0.0.0/0 on 22/3389)
#   - No public RDS
#   - No star-star IAM (Action:* + Resource:*)
#   - No long-lived IAM access keys in templates
#   - KMS keys must have key rotation enabled

s3_buckets[name] := res if {
	some name, res in input.Resources
	res.Type == "AWS::S3::Bucket"
}

# --- Public exposure: S3 canned ACL ---
deny contains msg if {
	some name, res in s3_buckets
	acl := res.Properties.AccessControl
	acl in {"PublicRead", "PublicReadWrite", "AuthenticatedRead"}
	msg := sprintf("CSPM: S3 bucket '%s' uses public AccessControl '%s'", [name, acl])
}

# --- Public exposure: S3 without full public-access block ---
deny contains msg if {
	some name, res in s3_buckets
	not fully_blocked(res)
	msg := sprintf("CSPM: S3 bucket '%s' is missing a complete PublicAccessBlockConfiguration", [name])
}

fully_blocked(res) if {
	pab := res.Properties.PublicAccessBlockConfiguration
	pab.BlockPublicAcls == true
	pab.BlockPublicPolicy == true
	pab.IgnorePublicAcls == true
	pab.RestrictPublicBuckets == true
}

# --- Encryption: S3 must have BucketEncryption ---
deny contains msg if {
	some name, res in s3_buckets
	not res.Properties.BucketEncryption
	msg := sprintf("CSPM: S3 bucket '%s' has no BucketEncryption (CMK required)", [name])
}

# --- Encryption: S3 must use aws:kms (not AES256 / aws:kms:dsse alone without CMK) ---
deny contains msg if {
	some name, res in s3_buckets
	rule := s3_sse_default(res)
	rule.SSEAlgorithm != "aws:kms"
	msg := sprintf("CSPM: S3 bucket '%s' uses SSEAlgorithm '%s' — customer-managed KMS (aws:kms) required", [name, rule.SSEAlgorithm])
}

# --- Encryption: S3 aws:kms must reference a CMK id ---
deny contains msg if {
	some name, res in s3_buckets
	rule := s3_sse_default(res)
	rule.SSEAlgorithm == "aws:kms"
	not rule.KMSMasterKeyID
	msg := sprintf("CSPM: S3 bucket '%s' uses aws:kms without KMSMasterKeyID (CMK required)", [name])
}

s3_sse_default(res) := rule if {
	some cfg in res.Properties.BucketEncryption.ServerSideEncryptionConfiguration
	rule := cfg.ServerSideEncryptionByDefault
}

# --- Network: SSH from the world ---
deny contains msg if {
	some name, res in input.Resources
	res.Type == "AWS::EC2::SecurityGroup"
	some rule in res.Properties.SecurityGroupIngress
	rule.FromPort == 22
	rule.CidrIp == "0.0.0.0/0"
	msg := sprintf("CSPM: SecurityGroup '%s' allows SSH (22) from 0.0.0.0/0", [name])
}

# --- Network: RDP from the world ---
deny contains msg if {
	some name, res in input.Resources
	res.Type == "AWS::EC2::SecurityGroup"
	some rule in res.Properties.SecurityGroupIngress
	rule.FromPort == 3389
	rule.CidrIp == "0.0.0.0/0"
	msg := sprintf("CSPM: SecurityGroup '%s' allows RDP (3389) from 0.0.0.0/0", [name])
}

# --- Data stores: public RDS ---
deny contains msg if {
	some name, res in input.Resources
	res.Type == "AWS::RDS::DBInstance"
	res.Properties.PubliclyAccessible == true
	msg := sprintf("CSPM: RDS instance '%s' is PubliclyAccessible — private networks only", [name])
}

# --- IAM least privilege: Action:* + Resource:* ---
deny contains msg if {
	some name, res in input.Resources
	res.Type in {"AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}
	stmt := policy_statements(res)[_]
	has_wildcard(stmt.Action)
	has_wildcard(stmt.Resource)
	stmt.Effect == "Allow"
	msg := sprintf("CSPM: IAM resource '%s' grants Action:* on Resource:* (star-star)", [name])
}

# --- Secrets / credentials: no long-lived IAM access keys in IaC ---
deny contains msg if {
	some name, res in input.Resources
	res.Type == "AWS::IAM::AccessKey"
	msg := sprintf("CSPM: IAM AccessKey '%s' is prohibited — use short-lived credentials / workload identity", [name])
}

# --- Encryption: KMS keys must rotate ---
deny contains msg if {
	some name, res in input.Resources
	res.Type == "AWS::KMS::Key"
	not res.Properties.EnableKeyRotation == true
	msg := sprintf("CSPM: KMS key '%s' must have EnableKeyRotation: true", [name])
}

policy_statements(res) := s if {
	res.Type == "AWS::IAM::Role"
	s := res.Properties.Policies[_].PolicyDocument.Statement
}

policy_statements(res) := res.Properties.PolicyDocument.Statement if {
	res.Type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}
}

has_wildcard(v) if v == "*"

has_wildcard(v) if {
	is_array(v)
	v[_] == "*"
}
