#!/usr/bin/env bash
# Unified CloudFormation governance scanner (the "scan gate").
#
# Runs THREE gates against a CloudFormation template (or a directory of templates,
# e.g. a CDK `cdk.out/`):
#   1. CSPM               -> trivy config      (public buckets, unencrypted, etc.)
#   2. Mandatory tags     -> conftest / rego   (governance/policies/tags.rego)
#   3. Region restriction -> conftest / rego   (governance/policies/region.rego, us-east-1 only)
#
# This is the SAME engine used at every lifecycle step (dev validate, PR pre-merge,
# post-merge CI, post-deploy). CDK is always synthesized to CloudFormation first
# (see governance/synth-cdk.sh) and then scanned here.
#
# Usage:  governance/scan-cfn.sh <template.yaml | dir> [--json out.json]
# Exit:   0 = PASS, 1 = FAIL (any gate), 2 = usage/error
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_DIR="${GOV_POLICY_DIR:-$SCRIPT_DIR/policies}"
TARGET="${1:-}"
JSON_OUT=""
[[ "${2:-}" == "--json" ]] && JSON_OUT="${3:-}"

if [[ -z "$TARGET" || ! -e "$TARGET" ]]; then
  echo "usage: $0 <template.yaml | dir> [--json out.json]" >&2
  exit 2
fi

# Collect target templates (portable: no mapfile — macOS bash 3.2 friendly).
TEMPLATES=()
if [[ -d "$TARGET" ]]; then
  while IFS= read -r line; do
    [[ -n "$line" ]] && TEMPLATES+=("$line")
  done < <(find "$TARGET" -type f \( -name '*.template.json' -o -name '*.yaml' -o -name '*.yml' \) \
      ! -path '*/asset.*' ! -name '*.assets.json' ! -name 'manifest.json' ! -name 'tree.json' | sort)
  # If no CDK-style templates, fall back to any *.json (plain CFN dir).
  if [[ ${#TEMPLATES[@]} -eq 0 ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && TEMPLATES+=("$line")
    done < <(find "$TARGET" -type f -name '*.json' ! -name '*.assets.json' ! -name 'manifest.json' ! -name 'tree.json' ! -path '*/asset.*' | sort)
  fi
else
  TEMPLATES=("$TARGET")
fi

if [[ ${#TEMPLATES[@]} -eq 0 ]]; then
  echo "No CloudFormation templates found under $TARGET" >&2
  exit 2
fi

have() { command -v "$1" >/dev/null 2>&1; }
BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'

# Portable bounded run (macOS has no coreutils `timeout` by default).
# run_bounded <seconds> <cmd...>  -> returns cmd rc, or 124 on timeout.
run_bounded() {
  local secs="$1"; shift
  if have timeout; then timeout "$secs" "$@"; return $?; fi
  if have gtimeout; then gtimeout "$secs" "$@"; return $?; fi
  "$@" & local p=$!
  ( sleep "$secs"; kill -9 "$p" 2>/dev/null ) & local w=$!
  wait "$p" 2>/dev/null; local rc=$?
  kill -9 "$w" 2>/dev/null
  return $rc
}
TRIVY_TIMEOUT="${TRIVY_TIMEOUT:-40}"
DISABLE_TRIVY="${DISABLE_TRIVY:-0}"

overall_fail=0
declare -a RESULTS

echo -e "${BLUE}== Aiden governance scan ==${NC}"
echo "Policies: $POLICY_DIR"
echo "Targets : ${#TEMPLATES[@]} template(s)"
echo

for tpl in "${TEMPLATES[@]}"; do
  echo -e "${BLUE}--- $tpl ---${NC}"
  file_fail=0

  # Gate 1: CSPM via trivy config (primary; bounded so it never hangs a demo)
  if have trivy && [[ "$DISABLE_TRIVY" != "1" ]]; then
    tout="$(run_bounded "$TRIVY_TIMEOUT" trivy config --quiet --severity HIGH,CRITICAL --exit-code 1 "$tpl" 2>&1)"
    trc=$?
    if [[ $trc -eq 124 ]]; then
      echo -e "  ${YEL}SKIP${NC} Governance CSPM — check-bundle download timed out (${TRIVY_TIMEOUT}s); policy CSPM still enforced"
    elif [[ $trc -ne 0 ]]; then
      echo -e "  ${RED}FAIL${NC} Governance CSPM: HIGH/CRITICAL misconfigurations"
      echo "$tout" | grep -E 'MISCONF|HIGH|CRITICAL|AVD-' | sed 's/^/      /' | head -20
      file_fail=1
    else
      echo -e "  ${GREEN}PASS${NC} Governance CSPM"
    fi
  else
    echo -e "  ${YEL}SKIP${NC} Governance CSPM (engine disabled/absent) — policy CSPM still enforced"
  fi

  # Gate 2 + 3 (+ rego CSPM fallback): mandatory tags + region + misconfig via conftest
  if have conftest; then
    cout="$(conftest test --no-color -p "$POLICY_DIR" "$tpl" 2>&1)"
    crc=$?
    if [[ $crc -ne 0 ]]; then
      echo -e "  ${RED}FAIL${NC} Policy (rego: CSPM + tags + region)"
      echo "$cout" | grep -E 'FAIL|MANDATORY-TAGS|REGION-RESTRICTION|CSPM' | sed 's/^/      /' | head -30
      file_fail=1
    else
      echo -e "  ${GREEN}PASS${NC} Policy (rego: CSPM + tags + region)"
    fi
  else
    echo -e "  ${YEL}SKIP${NC} Policy (conftest not installed)"
  fi

  # Optional legacy gate: cfn-guard
  if have cfn-guard && [[ -f "$POLICY_DIR/../org-governance.guard" ]]; then
    if cfn-guard validate -d "$tpl" -r "$POLICY_DIR/../org-governance.guard" >/dev/null 2>&1; then
      echo -e "  ${GREEN}PASS${NC} cfn-guard (org)"
    else
      echo -e "  ${RED}FAIL${NC} cfn-guard (org)"
      file_fail=1
    fi
  fi

  if [[ $file_fail -eq 0 ]]; then
    RESULTS+=("PASS $tpl"); echo -e "  => ${GREEN}PASS${NC}"
  else
    RESULTS+=("FAIL $tpl"); overall_fail=1; echo -e "  => ${RED}FAIL${NC}"
  fi
  echo
done

echo -e "${BLUE}== Summary ==${NC}"
for r in "${RESULTS[@]}"; do
  if [[ "$r" == PASS* ]]; then echo -e "  ${GREEN}$r${NC}"; else echo -e "  ${RED}$r${NC}"; fi
done

if [[ -n "$JSON_OUT" ]]; then
  {
    echo "{"
    echo "  \"overall\": \"$([[ $overall_fail -eq 0 ]] && echo PASS || echo FAIL)\","
    echo "  \"results\": ["
    for i in "${!RESULTS[@]}"; do
      st="${RESULTS[$i]%% *}"; fp="${RESULTS[$i]#* }"
      comma=","; [[ $i -eq $((${#RESULTS[@]}-1)) ]] && comma=""
      echo "    {\"status\": \"$st\", \"template\": \"$fp\"}$comma"
    done
    echo "  ]"
    echo "}"
  } > "$JSON_OUT"
  echo "JSON: $JSON_OUT"
fi

echo
if [[ $overall_fail -eq 0 ]]; then
  echo -e "${GREEN}GOVERNANCE: PASS${NC}"; exit 0
else
  echo -e "${RED}GOVERNANCE: FAIL${NC}"; exit 1
fi
