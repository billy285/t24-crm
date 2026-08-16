#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() {
  printf 'BUILD_ONCE_ERROR: %s\n' "$*" >&2
  exit 1
}

for tool in git python3 docker sha256sum find sort date tee stat awk mkdir; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool is unavailable: $tool"
done

[[ "${GITHUB_REPOSITORY:-}" == "billy285/t24-crm" ]] || die "unexpected repository"
[[ "${GITHUB_REF_NAME:-}" == "agent/crm-mobile-pwa-build-once-20260817" ]] || die "unexpected controller branch"
[[ "${RUNNER_OS:-}" == "Linux" ]] || die "candidate must be built on the approved Linux runner"
[[ -d source/.git && -d control/.git ]] || die "required isolated checkouts are missing"

artifact_dir="$GITHUB_WORKSPACE/candidate-artifact"
scratch_dir="$RUNNER_TEMP/t24-mobile-pwa-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
[[ ! -e "$artifact_dir" && ! -e "$scratch_dir" ]] || die "candidate output path already exists"
mkdir -m 700 "$artifact_dir" "$scratch_dir"

cleanup() {
  set +e
  if [[ -n "${candidate_container:-}" ]]; then
    docker rm -f "$candidate_container" >/dev/null 2>&1 || true
  fi
  if [[ -n "${image_id:-}" ]]; then
    docker image rm -f "$image_id" >/dev/null 2>&1 || true
  fi
  docker image rm -f "$CANDIDATE_TAG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

python3 -I control/.github/scripts/mobile_pwa_build_once.py validate-source \
  source "$artifact_dir/source-validation.txt"

resolve_manifest() {
  local ref="$1"
  local output="$2"
  docker buildx imagetools inspect --raw "$ref" >"$output"
  [[ -s "$output" ]] || die "empty registry manifest for $ref"
  sha256sum "$output" | awk '{print $1}'
}

syntax_ref='docker/dockerfile:1'
node_ref='node:22-bookworm-slim'
python_ref='python:3.10-slim'
syntax_digest="$(resolve_manifest "$syntax_ref" "$scratch_dir/dockerfile-frontend.manifest.json")"
node_digest="$(resolve_manifest "$node_ref" "$scratch_dir/node.manifest.json")"
python_digest="$(resolve_manifest "$python_ref" "$scratch_dir/python.manifest.json")"

python3 -I control/.github/scripts/mobile_pwa_build_once.py rewrite-dockerfile \
  source/app/Dockerfile "$artifact_dir/Dockerfile.release" \
  "$syntax_digest" "$node_digest" "$python_digest"

effective_dockerfile_sha="$(sha256sum "$artifact_dir/Dockerfile.release" | awk '{print $1}')"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
build_started_at="$created_at"
run_identity="github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"

python3 -I control/.github/scripts/mobile_pwa_build_once.py write-base-evidence \
  "$artifact_dir/base-image-digests.env" \
  "$syntax_ref" "$syntax_digest" \
  "$node_ref" "$node_digest" \
  "$python_ref" "$python_digest"

build_command=(
  docker build
  --no-cache
  --pull=false
  --platform "$BUILD_PLATFORM"
  --file "$artifact_dir/Dockerfile.release"
  --tag "$CANDIDATE_TAG"
  --label "org.opencontainers.image.source=https://github.com/billy285/t24-crm"
  --label "org.opencontainers.image.revision=$SOURCE_COMMIT"
  --label "org.opencontainers.image.ref.name=codex/crm-mobile-pwa-phase0-integration-20260817"
  --label "org.opencontainers.image.created=$created_at"
  --label "org.opencontainers.image.title=T24 CRM Mobile PWA Candidate"
  --label "org.opencontainers.image.version=75997c6"
  --label "com.t24.git.tree=$SOURCE_ROOT_TREE"
  --label "com.t24.git.app-tree=$SOURCE_APP_TREE"
  --label "com.t24.source.archive.sha256=$SOURCE_ARCHIVE_SHA256"
  --label "com.t24.dockerfile.original.sha256=$ORIGINAL_DOCKERFILE_SHA256"
  --label "com.t24.dockerfile.effective.sha256=$effective_dockerfile_sha"
  --label "com.t24.base.dockerfile.digest=sha256:$syntax_digest"
  --label "com.t24.base.node.digest=sha256:$node_digest"
  --label "com.t24.base.python.digest=sha256:$python_digest"
  --label "com.t24.release.run-id=$run_identity"
  source/app
)
printf '%q ' "${build_command[@]}" >"$artifact_dir/build-command.txt"
printf '\n' >>"$artifact_dir/build-command.txt"

set +e
"${build_command[@]}" 2>&1 | tee "$artifact_dir/build.log"
build_status=${PIPESTATUS[0]}
set -e
[[ "$build_status" -eq 0 ]] || die "docker build failed with status $build_status"

build_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
image_id="$(docker image inspect --format '{{.Id}}' "$CANDIDATE_TAG")"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "candidate image has an invalid full image ID"

docker image inspect "$image_id" >"$artifact_dir/image-inspect.json"
docker version >"$artifact_dir/docker-version.txt"
docker buildx version >"$artifact_dir/buildx-version.txt"

candidate_container="$(docker create --platform "$BUILD_PLATFORM" "$image_id")"
[[ "$candidate_container" =~ ^[0-9a-f]{64}$ ]] || die "candidate inspection container was not created"
docker export "$candidate_container" >"$scratch_dir/candidate-rootfs.tar"

python3 -I control/.github/scripts/mobile_pwa_build_once.py inventory \
  "$scratch_dir/candidate-rootfs.tar" "$artifact_dir/candidate-image-files.sha256"
python3 -I control/.github/scripts/mobile_pwa_build_once.py verify-inventory \
  "$scratch_dir/candidate-rootfs.tar" "$artifact_dir/candidate-image-files.sha256"

docker image rm "$CANDIDATE_TAG" >/dev/null
docker save "$image_id" --output "$artifact_dir/t24-mobile-pwa-candidate-75997c6.docker.tar"

python3 -I control/.github/scripts/mobile_pwa_build_once.py validate-save \
  "$artifact_dir/t24-mobile-pwa-candidate-75997c6.docker.tar" "$image_id" "$SOURCE_COMMIT"

docker rm "$candidate_container" >/dev/null
candidate_container=''

build_log_sha="$(sha256sum "$artifact_dir/build.log" | awk '{print $1}')"
base_evidence_sha="$(sha256sum "$artifact_dir/base-image-digests.env" | awk '{print $1}')"
inventory_sha="$(sha256sum "$artifact_dir/candidate-image-files.sha256" | awk '{print $1}')"
archive_sha="$(sha256sum "$artifact_dir/t24-mobile-pwa-candidate-75997c6.docker.tar" | awk '{print $1}')"
archive_size="$(stat -c %s "$artifact_dir/t24-mobile-pwa-candidate-75997c6.docker.tar")"

python3 -I control/.github/scripts/mobile_pwa_build_once.py write-provenance \
  "$artifact_dir/build-provenance.env" \
  "$image_id" "$effective_dockerfile_sha" "$base_evidence_sha" \
  "$build_log_sha" "$inventory_sha" "$archive_sha" "$archive_size" \
  "$build_started_at" "$build_finished_at" "$run_identity"

python3 -I control/.github/scripts/mobile_pwa_build_once.py artifact-manifest \
  "$artifact_dir" "$artifact_dir/ARTIFACTS.sha256"

printf 'BUILD_ONCE_PASS image_id=%s archive_sha256=%s files_manifest_sha256=%s\n' \
  "$image_id" "$archive_sha" "$inventory_sha"
