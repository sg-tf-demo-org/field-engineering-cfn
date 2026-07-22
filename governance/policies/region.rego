package main

import rego.v1

# Region-restriction gate.
# Only us-east-1 is permitted. Any other AWS region token found anywhere in the
# template (properties, ARNs, parameter defaults, mappings) is flagged.
# Fail-closed.

allowed_region := "us-east-1"

region_pattern := `(?:us|eu|ap|sa|ca|me|af|il)-(?:gov-)?(?:east|west|north|south|central|northeast|southeast|northwest|southwest)-[0-9]`

deny contains msg if {
	walk(input, [path, value])
	is_string(value)
	found := regex.find_n(region_pattern, value, -1)[_]
	found != allowed_region
	loc := concat("/", [sprintf("%v", [p]) | some p in path])
	msg := sprintf("REGION-RESTRICTION: disallowed region '%s' found at %s — only %s is permitted", [found, loc, allowed_region])
}
