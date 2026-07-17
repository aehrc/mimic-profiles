#!/usr/bin/env bash
#
# Publish the IG's conformance resources (CodeSystems, ValueSets, and
# StructureDefinitions) to a FHIR R4 server. For each resource, any server copy
# sharing the same canonical URL is deleted first, then the build-output copy is
# uploaded by its resource id. Terminology is published before
# StructureDefinitions so that terminology a profile binds to is present first.
# The run fails fast on the first unexpected HTTP response.
#
# Author: John Grimes.

set -euo pipefail

# Print usage information to stderr.
usage() {
  echo "Usage: $0 <fhir-base-url> <resource-dir>" >&2
  echo >&2
  echo "  <fhir-base-url>  FHIR R4 base URL, e.g. http://velonto.dw.csiro.au/fhir." >&2
  echo "  <resource-dir>   Directory holding CodeSystem-*.json, ValueSet-*.json," >&2
  echo "                   and StructureDefinition-*.json." >&2
}

# Report a failed HTTP interaction and exit non-zero.
fail() {
  local file="$1" operation="$2" status="$3" body="$4"
  echo "ERROR: ${operation} failed for ${file}" >&2
  echo "  HTTP status: ${status}" >&2
  echo "  Response body: ${body}" >&2
  exit 1
}

# Verify both arguments are present.
if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

base_url="$1"
resource_dir="$2"

# Strip a single trailing slash from the base URL if present.
base_url="${base_url%/}"

# Verify the required tools are on PATH.
for tool in curl jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool '${tool}' is not on PATH." >&2
    exit 1
  fi
done

# Verify the resource directory exists.
if [[ ! -d "$resource_dir" ]]; then
  echo "ERROR: resource directory '${resource_dir}' does not exist." >&2
  exit 1
fi

# Collect the conformance files. Terminology (CodeSystems then ValueSets) comes
# before StructureDefinitions so that terminology a profile binds to is
# published first. A nullglob keeps the arrays empty rather than leaving the
# literal glob pattern when nothing matches.
shopt -s nullglob
files=("$resource_dir"/CodeSystem-*.json "$resource_dir"/ValueSet-*.json \
  "$resource_dir"/StructureDefinition-*.json)
shopt -u nullglob

# Verify at least one matching file was found.
if [[ ${#files[@]} -eq 0 ]]; then
  echo "ERROR: no CodeSystem-*.json, ValueSet-*.json, or StructureDefinition-*.json files in '${resource_dir}'." >&2
  exit 1
fi

echo "Publishing ${#files[@]} conformance resources to ${base_url}."

for file in "${files[@]}"; do
  # Read the resource type, id, and canonical URL from the resource itself.
  resource_type="$(jq -r '.resourceType' "$file")"
  resource_id="$(jq -r '.id' "$file")"
  canonical_url="$(jq -r '.url' "$file")"

  # Guard against malformed resources missing any required field.
  if [[ -z "$resource_type" || "$resource_type" == "null" \
     || -z "$resource_id" || "$resource_id" == "null" \
     || -z "$canonical_url" || "$canonical_url" == "null" ]]; then
    echo "ERROR: ${file} is missing resourceType, id, or url." >&2
    exit 1
  fi

  # Conditionally delete every server copy sharing this canonical URL. A 404
  # means nothing matched, which is not an error; a 412 (multiple matches
  # rejected) or any other unexpected status fails the run.
  echo "Deleting existing ${resource_type} with url=${canonical_url}."
  delete_response="$(curl -sS -G -X DELETE \
    -w $'\n%{http_code}' \
    --data-urlencode "url=${canonical_url}" \
    "${base_url}/${resource_type}")"
  delete_status="${delete_response##*$'\n'}"
  delete_body="${delete_response%$'\n'*}"
  case "$delete_status" in
    200 | 204 | 404) ;;
    *) fail "$file" "conditional delete" "$delete_status" "$delete_body" ;;
  esac

  # Upload the build-output copy by its resource id.
  echo "Uploading ${resource_type}/${resource_id} from ${file}."
  put_response="$(curl -sS -X PUT \
    -w $'\n%{http_code}' \
    -H "Content-Type: application/fhir+json" \
    --data-binary "@${file}" \
    "${base_url}/${resource_type}/${resource_id}")"
  put_status="${put_response##*$'\n'}"
  put_body="${put_response%$'\n'*}"
  case "$put_status" in
    200 | 201) ;;
    *) fail "$file" "update by id" "$put_status" "$put_body" ;;
  esac
done

echo "Done. Published ${#files[@]} conformance resources."
