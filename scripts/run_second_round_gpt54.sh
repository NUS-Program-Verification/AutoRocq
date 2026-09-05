#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/proof-search/configs/gpt54.json"
API_KEY_FILE="$ROOT/.codex/OPENAPI"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  if [[ ! -s "$API_KEY_FILE" ]]; then
    printf 'Set OPENAI_API_KEY or place the key in %s\n' "$API_KEY_FILE" >&2
    exit 2
  fi
  OPENAI_API_KEY="$(tr -d '\r\n' < "$API_KEY_FILE")"
  export OPENAI_API_KEY
fi

benchmarks=(
  "standard_strcmp_ground/strcmp_assert_reachability.v"
  "rew/main_loop_invariant_3_preserved.v"
  "rewrev/main_loop_invariant_inv_a_val1_preserved.v"
  "sendmail-close-angle/main_assert_rte_signed_overflow_4.v"
  "standard_init4_ground-2/main_loop_invariant_7_preserved.v"
)

successes=0
failures=0
failed_benchmarks=()

cd "$ROOT/proof-search"

for benchmark in "${benchmarks[@]}"; do
  proof_file="$ROOT/AutoRocq-bench/benchmarks/svcomp/$benchmark"
  printf '\n===== GPT-5.4: %s =====\n' "$benchmark"

  if python3 -m main "$proof_file" --config "$CONFIG" --max-steps 100; then
    ((successes += 1))
  else
    ((failures += 1))
    failed_benchmarks+=("$benchmark")
  fi
done

printf '\n===== Second-round summary =====\n'
printf 'Succeeded: %d/%d\n' "$successes" "${#benchmarks[@]}"
printf 'Failed:    %d/%d\n' "$failures" "${#benchmarks[@]}"

if ((failures > 0)); then
  printf 'Failed benchmarks:\n'
  printf '  %s\n' "${failed_benchmarks[@]}"
fi

exit "$failures"
