#!/usr/bin/env bash
# Plan mode parses both real argument vectors without configuring or compiling.
set -euo pipefail
if [[ $# != 4 || ( $1 != plan && $1 != build ) ]]; then
  echo "usage: bash build-pair.sh plan|build ORT_SOURCE NEW_WORK_DIR EXPERIMENTAL_CONFIG" >&2
  exit 2
fi
mode=$1
recipe=$(cd "$(dirname "$0")" && pwd)
source_dir=$(realpath "$2")
work=$(realpath -m "$3")
config=$(realpath "$4")
commit=8f0278c77bf44b0cc83c098c6c722b92a36ac4b5
tree=5ea4a49d0be5e5a620cabaa01f85d924b2fa5995
printf '%s  %s\n' 1601aecf861212c77c9a92395369f4b89035b75b3824e657b3e45ab00bfcc826 "$config" | sha256sum -c -
cd "$source_dir"
job_count=${JOBS:-2}
common=(--config Release --update --build --parallel "$job_count" --skip_tests
        --skip_submodule_sync --cmake_generator Ninja --build_shared_lib --target onnxruntime
        --compile_no_warning_as_error --cmake_extra_defines onnxruntime_BUILD_UNIT_TESTS=OFF)
if [[ $(id -u) == 0 ]]; then common+=(--allow_running_as_root); fi
if [[ $mode == build ]]; then
  [[ $(uname -sm) == 'Linux x86_64' ]]
  [[ $(git rev-parse HEAD) == "$commit" && $(git rev-parse 'HEAD^{tree}') == "$tree" ]]
  [[ -z $(git status --porcelain --untracked-files=no) ]]
  git submodule status --recursive | awk 'substr($0, 1, 1) != " " {wrong=1} END {exit wrong}'
  python3 -c 'import flatbuffers; assert flatbuffers.__version__ == "25.2.10"'
  python3 tools/ci_build/reduce_op_kernels.py --help >/dev/null
  python3 tools/ci_build/build.py --help >/dev/null
  mkdir "$work"
  mkdir -p "$work/evidence"/{baseline,candidate}
  printf '%s\n' NOT_RUN | tee "$work/evidence/baseline/result.txt" > "$work/evidence/candidate/result.txt"
  { uname -sm; python3 --version; cmake --version; ninja --version
    "${CC:-cc}" --version; "${CXX:-c++}" --version; ld --version; readelf --version
    git rev-parse HEAD 'HEAD^{tree}'; git submodule status --recursive
    sha256sum cmake/deps.txt "$config"; } > "$work/evidence/environment.txt"
  cp cmake/deps.txt "$work/evidence/deps.txt"
fi
for side in baseline candidate; do
  args=(--build_dir "$work/build-$side" "${common[@]}")
  if [[ $side == candidate ]]; then args+=(--include_ops_by_config "$config"); fi
  if [[ $mode == plan ]]; then
    printf '%s: ' "$side"; printf '%q ' python3 tools/ci_build/build.py "${args[@]}"; printf '\n'
    PYTHONPATH="$source_dir/tools/ci_build:$source_dir/tools/python${PYTHONPATH:+:$PYTHONPATH}" \
      python3 -c 'from build_args import parse_arguments; from sys import argv; a=parse_arguments(); print("target",a.targets,"reduced",a.include_ops_by_config,"minimal",a.minimal_build,"type_reduction",a.enable_reduced_operator_type_support,"pybind",a.enable_pybind,"training",a.enable_training,"cuda",a.use_cuda,"tests",a.test,"extra",a.cmake_extra_defines)' "${args[@]}"
    continue
  fi
  evidence="$work/evidence/$side"
  printf '%q ' python3 tools/ci_build/build.py "${args[@]}" > "$evidence/command.txt"
  printf '\n' >> "$evidence/command.txt"
  build_dir="$work/build-$side/Release"
  printf '%s\n' STARTED > "$evidence/result.txt"
  build_status=0
  python3 tools/ci_build/build.py "${args[@]}" > "$evidence/build.log" 2>&1 || build_status=$?
  # Save the final edge and its rule/variables even if a subsequent compile or link fails.
  for plan_file in CMakeCache.txt build.ninja CMakeFiles/rules.ninja; do
    if [[ -f $build_dir/$plan_file ]]; then
      (cd "$build_dir" && cp --parents "$plan_file" "$evidence/")
    fi
  done
  compare_status=0
  if [[ $side == candidate ]]; then
    reduced="$build_dir/op_reduction.generated"
    if [[ -d $reduced ]]; then
      (cd "$reduced" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum) > "$evidence/generated.sha256"
      diff -u "$recipe/expected-generated.sha256" "$evidence/generated.sha256" \
        > "$evidence/generated-diff.txt" || compare_status=$?
    else
      echo "op_reduction.generated absent" > "$evidence/generated-diff.txt"
      compare_status=1
    fi
  fi
  if (( build_status != 0 )); then
    printf '%s\n' BUILD_FAILED > "$evidence/result.txt"
    echo "$side failed; see $evidence/build.log" >&2
    exit "$build_status"
  fi
  if (( compare_status != 0 )); then
    printf '%s\n' GENERATED_MISMATCH > "$evidence/result.txt"
    echo "Generated sources differ from the reference; see $evidence/generated-diff.txt" >&2
    exit "$compare_status"
  fi
  lib="$build_dir/libonnxruntime.so"
  { sha256sum "$lib"; stat -Lc 'bytes=%s' "$lib"; readelf -hW "$lib"; readelf -dW "$lib"; } > "$evidence/elf.txt"
  if ! ninja -C "$build_dir" -t commands onnxruntime | awk '/ -shared / && / -o ([^ ]*\/)?libonnxruntime\.so([.0-9]*)?( |$)/ {print}' > "$evidence/link.txt" || [[ ! -s $evidence/link.txt ]]; then
    echo "Link line not captured; inspect the final shared-library rule in build.ninja." > "$evidence/link.txt"
  fi
  python3 "$recipe/record_identity.py" side "$work/evidence" "$source_dir" "$config" "$side" "$lib"
  printf '%s\n' SUCCESS > "$evidence/result.txt"
done
if [[ $mode == build ]]; then
  python3 "$recipe/record_identity.py" pair "$work/evidence"
fi
