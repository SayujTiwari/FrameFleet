#!/usr/bin/env bash

set -euo pipefail

PROJECT_NAME="${FRAMEFLEET_RECOVERY_PROJECT:-framefleet-recovery-test}"
API_PORT="${FRAMEFLEET_RECOVERY_PORT:-8004}"
LEASE_SECONDS="${FRAMEFLEET_RECOVERY_LEASE_SECONDS:-6}"
ROOT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_PATH="/tmp/framefleet-recovery-source.mp4"
OUTPUT_PATH="/tmp/framefleet-recovery-output.mp4"
WORKER_A_CONTAINER="${PROJECT_NAME}-worker-1"
WORKER_B_CONTAINER="${PROJECT_NAME}-worker-b"
API_URL="http://127.0.0.1:${API_PORT}"

export FRAMEFLEET_API_PORT="${API_PORT}"
export FRAMEFLEET_LEASE_SECONDS="${LEASE_SECONDS}"

LATEST_JOB_JSON=""
JOB_ID=""

cleanup() {
  docker unpause "${WORKER_A_CONTAINER}" >/dev/null 2>&1 || true
  docker rm --force "${WORKER_B_CONTAINER}" >/dev/null 2>&1 || true
  docker compose -p "${PROJECT_NAME}" down --volumes --remove-orphans
  rm -f "${SOURCE_PATH}" "${OUTPUT_PATH}"
}

json_field() {
  python3 -c \
    'import json, sys; print(json.loads(sys.argv[1])[sys.argv[2]])' \
    "$1" "$2"
}

wait_for_job_to_start() {
  for _ in {1..120}; do
    LATEST_JOB_JSON="$(curl --silent --show-error \
      "${API_URL}/jobs/${JOB_ID}")"
    status="$(json_field "${LATEST_JOB_JSON}" status)"

    if [[ "${status}" == "processing" ]]; then
      return 0
    fi

    if [[ "${status}" == "failed" || "${status}" == "cancelled" ]]; then
      echo "Job entered unexpected status: ${status}" >&2
      return 1
    fi

    sleep 0.25
  done

  echo "Timed out waiting for the first worker to claim the job" >&2
  return 1
}

wait_for_job_to_finish() {
  for _ in {1..240}; do
    LATEST_JOB_JSON="$(curl --silent --show-error \
      "${API_URL}/jobs/${JOB_ID}")"
    status="$(json_field "${LATEST_JOB_JSON}" status)"

    if [[ "${status}" == "completed" ]]; then
      return 0
    fi

    if [[ "${status}" == "failed" || "${status}" == "cancelled" ]]; then
      echo "Recovered job entered unexpected status: ${status}" >&2
      return 1
    fi

    sleep 0.5
  done

  echo "Timed out waiting for the replacement worker" >&2
  return 1
}

wait_for_stale_rejection() {
  for _ in {1..30}; do
    worker_logs="$(docker logs "${WORKER_A_CONTAINER}" 2>&1 || true)"

    if [[ "${worker_logs}" == *"failed (stale)"* \
      || "${worker_logs}" == *"Ignored stale result"* ]]; then
      return 0
    fi

    sleep 0.5
  done

  echo "The original worker did not report rejecting its stale attempt" >&2
  return 1
}

trap cleanup EXIT
cd "${ROOT_DIRECTORY}"

echo "Starting isolated database and API on port ${API_PORT}..."
docker compose -p "${PROJECT_NAME}" up --build --detach database backend

echo "Generating a synthetic video that is slow enough to interrupt..."
docker run --rm --volume /tmp:/output "${PROJECT_NAME}-backend" \
  ffmpeg -v error \
  -f lavfi -i "testsrc2=size=1920x1080:rate=30" \
  -t 20 -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -y "/output/$(basename "${SOURCE_PATH}")"

echo "Creating the encoding job..."
job_json="$(curl --silent --show-error \
  --form "video=@${SOURCE_PATH};type=video/mp4" \
  --form "target_segment_seconds=20" \
  --form "output_resolution=original" \
  --form "quality=high" \
  "${API_URL}/jobs")"
JOB_ID="$(json_field "${job_json}" job_id)"

echo "Starting worker A and waiting for it to claim job ${JOB_ID}..."
docker compose -p "${PROJECT_NAME}" up --detach worker
wait_for_job_to_start

echo "Pausing worker A while it owns an active lease..."
docker pause "${WORKER_A_CONTAINER}" >/dev/null

echo "Waiting for the ${LEASE_SECONDS}-second lease to expire..."
sleep "$((LEASE_SECONDS + 2))"

echo "Starting worker B to reclaim the abandoned segment..."
docker compose -p "${PROJECT_NAME}" run --detach \
  --name "${WORKER_B_CONTAINER}" \
  --env FRAMEFLEET_WORKER_ID=recovery-worker-b \
  worker >/dev/null

wait_for_job_to_finish

worker_b_logs="$(docker logs "${WORKER_B_CONTAINER}" 2>&1)"

if [[ "${worker_b_logs}" != *"Reclaiming segment"* ]]; then
  echo "Worker B completed without recording a reclaimed lease" >&2
  exit 1
fi

echo "Resuming worker A so its fenced attempt can be rejected..."
docker unpause "${WORKER_A_CONTAINER}" >/dev/null
wait_for_stale_rejection

LATEST_JOB_JSON="$(curl --silent --show-error \
  "${API_URL}/jobs/${JOB_ID}")"
retry_count="$(json_field "${LATEST_JOB_JSON}" retry_count)"

if (( retry_count < 1 )); then
  echo "Expected the completed job to report at least one retry" >&2
  exit 1
fi

curl --silent --show-error --fail \
  --output "${OUTPUT_PATH}" \
  "${API_URL}/jobs/${JOB_ID}/download"

if [[ ! -s "${OUTPUT_PATH}" ]]; then
  echo "The recovered job produced no downloadable output" >&2
  exit 1
fi

python3 -c '
import json
import sys

job = json.loads(sys.argv[1])
performance = job["performance"] or {}

print("\nRecovery test passed")
print("  job: {}".format(job["job_id"]))
print("  status: {}".format(job["status"]))
print("  retries: {}".format(job["retry_count"]))
print("  output bytes: {}".format(job["output_file_size_bytes"]))
print("  elapsed seconds: {}".format(performance.get("elapsed_seconds")))
print("  realtime multiplier: {}".format(
    performance.get("realtime_multiplier")
))
print("  stale worker result: rejected")
' "${LATEST_JOB_JSON}"
