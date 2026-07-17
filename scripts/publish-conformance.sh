#!/usr/bin/env bash
#
# Publish the IG's conformance resources (CodeSystems, ValueSets, and
# StructureDefinitions) to a FHIR R4 server. For each resource, every server
# copy sharing the same canonical URL is deleted first (found by search and
# deleted individually by id, as the server does not support conditional
# delete), then the build-output copy is uploaded by its resource id. Deleting
# all matches first ensures the canonical URL resolves unambiguously.
# Terminology is published before StructureDefinitions so that terminology a
# profile binds to is present first. The run fails fast on the first
# unexpected HTTP response.
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

  # Delete every server copy sharing this canonical URL, so the URL resolves
  # unambiguously after upload. The server does not support conditional
  # delete, so matches are found by search and deleted individually by id.
  # The search-delete cycle repeats until no matches remain, which also
  # covers results paged beyond a single search response.
  encoded_url="$(jq -rn --arg url "$canonical_url" '$url | @uri')"
  attempts=0
  while :; do
    # Bound the search-delete cycle so a server that keeps returning matches
    # it will not delete cannot loop forever.
    attempts=$((attempts + 1))
    if [[ $attempts -gt 10 ]]; then
      echo "ERROR: matches for url=${canonical_url} remain after ${attempts} search-delete cycles." >&2
      exit 1
    fi

    search_response="$(curl -sS \
      -w $'\n%{http_code}' \
      -H "Accept: application/fhir+json" \
      "${base_url}/${resource_type}?url=${encoded_url}&_elements=id&_count=100")"
    search_status="${search_response##*$'\n'}"
    search_body="${search_response%$'\n'*}"
    if [[ "$search_status" != 200 ]]; then
      fail "$file" "search by url" "$search_status" "$search_body"
    fi

    # Collect the ids of the matched resources; stop once none remain. FHIR
    # ids contain no whitespace or glob characters, so word-splitting the jq
    # output into an array is safe (and portable to bash 3, unlike mapfile).
    # shellcheck disable=SC2207
    existing_ids=($(jq -r \
      '[.entry // [] | .[] | select(.search.mode != "include") | .resource.id] | .[]' \
      <<< "$search_body"))
    if [[ ${#existing_ids[@]} -eq 0 ]]; then
      break
    fi

    for existing_id in "${existing_ids[@]}"; do
      echo "Deleting existing ${resource_type}/${existing_id} with url=${canonical_url}."
      delete_response="$(curl -sS -X DELETE \
        -w $'\n%{http_code}' \
        "${base_url}/${resource_type}/${existing_id}")"
      delete_status="${delete_response##*$'\n'}"
      delete_body="${delete_response%$'\n'*}"
      case "$delete_status" in
        200 | 204 | 404) ;;
        *) fail "$file" "delete by id" "$delete_status" "$delete_body" ;;
      esac
    done
  done

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
