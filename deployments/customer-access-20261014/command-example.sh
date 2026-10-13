#!/usr/bin/env bash
# Reviewed server invocation template. This file does not upload/build a release.
# Execute only after an authenticated live preflight, exact source freeze, local
# payload build and independent review of all artifact hashes. Never put secrets
# in these variables. The caller must be root on the one pinned server.
set -euo pipefail

# Fresh 0700 directory containing protected 0600 release.py, manifest.json,
# payload.tar.gz. Never reuse a partially prepared directory.
: "${T24_CUSTOMER_RELEASE:?absolute fresh release directory required}"
: "${T24_CUSTOMER_HELPER_SHA:?reviewed release.py SHA256 required}"
: "${T24_CUSTOMER_MANIFEST_SHA:?reviewed manifest.json SHA256 required}"
: "${T24_CUSTOMER_PAYLOAD_SHA:?reviewed payload.tar.gz SHA256 required}"
: "${T24_CUSTOMER_PHASE:?prepare, activate or recover required}"

# This immutable retained receipt supplies ONLY private service/environment/DB
# identity pins. release.py revalidates them live on every boundary. CRM image,
# container, source inventory, nginx and public root are separately pinned in
# the new release.py; the historical CRM fields in this receipt are not used.
t24_private_preflight='/opt/t24-crm/releases/commission-service-month-preflight-20261013.json'
t24_private_preflight_sha='af9028f405deed4486628b8c709fe0157100a00a515e00840bdf760eec11f161'

[[ "$(id -u)" == 0 ]]
[[ "$(hostname)" == 'iZj6c4cj7edgnhdimts4l7Z' ]]
[[ "$T24_CUSTOMER_RELEASE" == /opt/t24-crm/releases/customer-access-* ]]
[[ "$T24_CUSTOMER_HELPER_SHA" =~ ^[a-f0-9]{64}$ ]]
printf '%s  %s\n' "$T24_CUSTOMER_HELPER_SHA" "$T24_CUSTOMER_RELEASE/release.py" | sha256sum --check --status

t24_release_args=(
  --phase "$T24_CUSTOMER_PHASE"
  --release "$T24_CUSTOMER_RELEASE"
  --manifest-sha256 "$T24_CUSTOMER_MANIFEST_SHA"
  --payload-sha256 "$T24_CUSTOMER_PAYLOAD_SHA"
  --preflight "$t24_private_preflight"
  --preflight-sha256 "$t24_private_preflight_sha"
)
case "$T24_CUSTOMER_PHASE" in
  prepare) ;;
  activate|recover)
    # Use the independently reviewed receipt_sha256 from prepare output,
    # never compute a new trusted value from a changed server file.
    : "${T24_CUSTOMER_PREPARED_SHA:?reviewed prepared.json SHA256 required}"
    t24_release_args+=(--review-sha256 "$T24_CUSTOMER_PREPARED_SHA")
    ;;
  *) exit 64 ;;
esac

# Recover handles only interrupted activations, never a successful release.
# It never restores the database. If new sharing/private/audit state changed,
# old authorization code is blocked and the candidate remains protected.
python3 "$T24_CUSTOMER_RELEASE/release.py" "${t24_release_args[@]}"
