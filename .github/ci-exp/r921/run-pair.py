"""固定六图的主机双库研究编排；仅 evidence/ 中的 UTF-8 文本用于交付。"""
import argparse
from datetime import datetime, timezone
from hashlib import file_digest
import json
import math
import os
import re
import shlex
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".part")
    pending.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def digest(path):
    with path.open("rb") as f:
        return file_digest(f, "sha256").hexdigest()


def verify_build(args):
    if args.baseline_library.samefile(args.candidate_library):
        raise ValueError("baseline 和 candidate 指向同一个文件")
    given = args.build_evidence
    pair_path = given / "pair-build-identity.json" if given.is_dir() else given
    pair = read_json(pair_path)
    build = pair_path.parent
    plan = ROOT / "build-plan"
    pins = read_json(plan / "plan-sources.json")
    expected = {"ortCommit": pins["ortCommit"], "ortTree": pins["ortRootTree"],
                "configSha256": digest(plan / "required-operators.config")}
    environment = (build / "environment.txt").read_text(encoding="utf-8").splitlines()
    if (pair["schema"] != 1 or any(pair[k] != v for k, v in expected.items())
            or not {expected["ortCommit"], expected["ortTree"]}.issubset(environment)
            or not any(line.lstrip("\\").startswith(expected["configSha256"] + "  ") for line in environment)):
        raise ValueError("双构建的源码、树、配置或环境身份不符")
    generated = digest(plan / "expected-generated.sha256")
    commands = {}
    for role, file in (("baseline", args.baseline_library), ("candidate", args.candidate_library)):
        side = build / role
        row = pair[role]
        reduced = role == "candidate"
        actual = digest(file)
        size = file.stat().st_size
        elf = (side / "elf.txt").read_text(encoding="utf-8").splitlines()
        command_file = side / "command.txt"
        command = shlex.split(command_file.read_text(encoding="utf-8"))
        has_option = command.count("--include_ops_by_config")
        if ((side / "result.txt").read_bytes() != b"SUCCESS\n" or row != read_json(side / "build-identity.json")
                or row["role"] != role or row["reduced"] is not reduced
                or any(row[k] != v for k, v in expected.items())
                or (row["libraryBytes"], row["librarySha256"]) != (size, actual)
                or len(elf) < 2 or not elf[0].lstrip("\\").startswith(actual + "  ") or elf[1] != f"bytes={size}"
                or row["commandSha256"] != digest(command_file) or has_option != int(reduced)):
            raise ValueError(f"{role} 源码、角色、成功状态、命令或 ELF 身份不符")
        if reduced:
            i = command.index("--include_ops_by_config")
            if (row["includeOpsConfigSha256"] != expected["configSha256"] or row["generatedMatch"] is not True
                    or row["generatedSha256"] != generated or digest(side / "generated.sha256") != generated
                    or (side / "generated-diff.txt").stat().st_size
                    or i+1 >= len(command)):
                raise ValueError("candidate 裁减配置或实生成清单不符")
            del command[i:i+2]
        elif any(row[k] is not None for k in ("includeOpsConfigSha256", "generatedMatch", "generatedSha256")):
            raise ValueError("baseline 带有裁减标记")
        i = command.index("--build_dir")
        if Path(command[i+1]).name != "build-" + role:
            raise ValueError(f"{role} 构建目录记录不符")
        del command[i:i+2]
        commands[role] = command
    if commands["baseline"] != commands["candidate"]:
        raise ValueError("两侧命令除输出目录和裁减参数外仍有差异")
    identity = ("IDENTICAL_ARTIFACT" if pair["baseline"]["librarySha256"] == pair["candidate"]["librarySha256"]
                else "DISTINCT_ARTIFACTS")
    return {"artifactIdentity": identity, "source": expected, "pairRecordSha256": digest(pair_path),
            "sides": {role: pair[role] for role in ("baseline", "candidate")}}


def verify_tools(args):
    identity = read_json(ROOT / "preprocess/source-identity.json")
    records = {args.kotlin_jars / file: spec for file, spec in identity["toolchain"]["compilerClasspath"].items()}
    records[args.json_jar] = identity["toolchain"]["jsonJar"]["json-20240303.jar"]
    for name, spec in identity["product"].items():
        if spec["compiled"]:
            records[ROOT / "product" / Path(name).name] = spec
    for name, spec in read_json(ROOT / "header-identity.json").items():
        records[ROOT / "include" / name] = spec
    for file, spec in records.items():
        if file.stat().st_size != spec["bytes"] or digest(file) != spec["sha256"]:
            raise ValueError(f"身份不符：{file.name}")
    return {"verifiedFiles": {p.name: spec["sha256"] for p, spec in records.items()},
            "build": verify_build(args)}


def stages(args):
    priv = args.work / "private"
    prep = ROOT / "preprocess"
    kt = read_json(prep / "source-identity.json")["toolchain"]["compilerClasspath"]
    compiler_cp = os.pathsep.join(str(args.kotlin_jars / name) for name in kt)
    stdlib = args.kotlin_jars / "kotlin-stdlib-2.4.0.jar"
    compilation_cp = os.pathsep.join(map(str, (stdlib, args.json_jar)))
    classes = priv / "classes"
    runtime_cp = os.pathsep.join(map(str, (classes, stdlib, args.json_jar)))
    runner = priv / "ort_runner"
    inputs = args.inputs
    py = sys.executable
    wheel, = (row["filename"] for row in read_json(ROOT / "INPUT-SOURCES.json")["inputs"]
              if row["filename"].endswith(".whl"))
    pair = ["--runner", runner, "--models", inputs, "--left-library", args.baseline_library,
            "--right-library", args.candidate_library]
    actions = [
        ("verify-inputs", [py, ROOT / "fetch_inputs.py", "--inputs", inputs]),
        ("verify-tools", None),
        ("compile-capi", ["c++", "-std=c++17", "-O2", "-I", ROOT / "include", ROOT / "ort_runner.cc",
                          "-ldl", "-o", runner]),
        ("compile-kotlin", ["java", "-cp", compiler_cp, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                            "-no-stdlib", "-no-reflect", "-classpath", compilation_cp, "-d", classes,
                            ROOT / "product/WhisperMel.kt", ROOT / "product/CompanionWordPiece.kt",
                            prep / "PrepareInputs.kt"]),
        ("fixture-cases", [py, prep / "fixture_cases.py", runtime_cp, inputs / "tokenizer.json", priv / "cases"]),
        ("public-wav-cases", [py, prep / "public_wav_cases.py", runtime_cp, inputs / "1.wav", priv / "real-cases"]),
        ("prepared", [py, ROOT / "prepared_probe.py", *pair, "--cases", priv / "cases", "--output", priv / "prepared"]),
        ("speech", [py, ROOT / "speech_probe.py", *pair, "--wav", inputs / "1.wav",
                    "--smart-cases", priv / "real-cases", "--output", priv / "speech"]),
        ("zipformer", [py, ROOT / "zipformer_probe.py", "--runner", runner, "--models", inputs,
                       "--library", args.baseline_library, "--candidate", args.candidate_library,
                       "--tokens", inputs / "tokens.txt", "--wav", inputs / "1.wav", "--wheel", inputs / wheel,
                       "--out", priv / "zipformer"]),
        ("aggregate", None),
    ]
    return {name: list(map(str, command)) if command else None for name, command in actions}


def bit_equal(comparison):
    return comparison.get("sameShapeType") is True and comparison.get("bitwiseEqual") is True


def counted_comparisons(values, names):
    return set(values) == set(names) and all(bit_equal(values[n]) for n in names)


def aggregate(evidence):
    prepared, speech, zipformer = [read_json(evidence / p / "result.json") for p in ("prepared", "speech", "zipformer")]
    cases = prepared["cases"]
    expected = {"empty-doc", "same-doc", "same-query", "mixed-doc", "long-doc",
                "silence-short", "synthetic-short", "synthetic-full", "synthetic-wrap"}
    bge_cases = {"empty-doc", "same-doc", "same-query", "mixed-doc", "long-doc"}
    bge_names = {"last_hidden_state", "sentence_embedding"}
    def prepared_case(row):
        bge = row["case"] in bge_cases
        names = bge_names if bge else {"logits"}
        return (row["model"] == ("bge" if bge else "smartTurn")
                and counted_comparisons(row["comparison"], names)
                and all(set(row["outputs"][side]) == names for side in ("left", "right"))
                and (not bge or bit_equal(row.get("normalizedClsComparison", {}))))
    documents = bge_cases - {"same-query"}
    rankings = prepared["bgeSimilarity"]
    def valid_ranking(row):
        scores = row["scores"]
        return (set(scores) == documents and all(math.isfinite(v) for v in scores.values())
                and row["descending"] == sorted(scores, key=scores.get, reverse=True))
    prepared_checks = {
        "nineFixedCases": len(cases) == 9 and {r["case"] for r in cases} == expected,
        "allRawOutputsBitwiseEqual": prepared["allRawOutputsBitwiseEqual"] is True,
        "caseComparisons": all(prepared_case(r) for r in cases),
        "sameBgeScoresAndOrder": prepared["sameBgeOrder"] is True and set(rankings) == {"left", "right"}
            and all(valid_ranking(row) for row in rankings.values())
            and rankings["left"]["descending"] == rankings["right"]["descending"]
            and all(struct.pack(">d", rankings["left"]["scores"][k]) == struct.pack(">d", rankings["right"]["scores"][k])
                    for k in documents),
    }
    vad = speech["silero"]
    scenarios = vad["scenarios"]
    vad_output_names = ("output", "stateN")
    # Warm-up and the four SmartTurn inputs are shared objects in speech_probe,
    # unlike Silero's recurrent inputs, which evolve independently per side.
    boundaries = {"unmuted": (400, 0, 0), "mute-frames-100-to-109": (393, 128, 10)}
    speech_checks = {
        "warmupSharedInputsBothOutputsBitwiseEqual": counted_comparisons(vad["warmupComparison"], vad_output_names),
        "bothScenariosPresent": len(scenarios) == 2 and {r["name"] for r in scenarios} ==
            {"unmuted", "mute-frames-100-to-109"},
        "allRecurrentInputsAndOutputsEqual": all(s["name"] in boundaries and s["frames"] == 640
            and (s["runCount"], s["residualNewSamples"], s["mutedFrames"]) == boundaries[s["name"]]
            and s["runCount"] == len(s["runs"]) and
            all(r["sameInputs"] is True and counted_comparisons(r["comparison"], vad_output_names)
                for r in s["runs"]) for s in scenarios),
        "fourSmartTurnCases": len(speech["smartTurn"]) == 4 and {r["case"] for r in speech["smartTurn"]} ==
            {"spoken-1s", "spoken-5p1s", "joined-full-8s", "joined-wrap-9s"},
        "allSmartTurnSharedInputsAndOutputsEqual": all(set(r["inputs"]) == {"input_features"}
            and all(set(r["outputs"][side]) == {"logits"} for side in ("left", "right")) and bit_equal(r["comparison"])
                                                     for r in speech["smartTurn"]),
    }
    left, right = (zipformer["sides"][name] for name in ("baseline", "candidate"))
    pc = zipformer["pair"]
    counts = pc["counts"]
    roles = ("encoder", "decoder", "joiner")
    expected_outputs = {"encoder": {"encoder_out", *(
        f"new_cached_{field}_{i}" for field in ("len", "avg", "key", "val", "val2", "conv1", "conv2") for i in range(5))},
                        "decoder": {"decoder_out"}, "joiner": {"logit"}}
    metrics = pc["outputMetrics"]
    expected_metrics = {role + ".equalInputs." + name: role for role, names in expected_outputs.items() for name in names}
    def complete_trace(trace):
        return set(trace) == set(roles) and all(re.fullmatch("[0-9a-f]{64}", value) for value in trace.values())
    zchecks = {
        "wholeFixtureAndDecisions": zipformer["fbankPcmFrames"] == 640 and zipformer["blocksBeforeFinish"] == 39
            and zipformer["blocksAfterFinish"] == 1 and all(s["runs"]["encoderRuns"] == 40 and s["runs"]["blank"] > 0
                and s["runs"]["emitted"] > 0 and bool(s["endpoints"]) for s in (left, right)),
        "matchedAllCallsWithSameInputs": all(counts.get(role + ".equalInputs", 0) ==
            left["runs"][role + "Runs"] == right["runs"][role + "Runs"] > 0 for role in ("encoder", "decoder", "joiner")),
        "noDifferentInputsOrOneSidedCalls": not pc["inputExceptions"] and all(
            n == 0 for k, n in counts.items() if k.endswith(".differentInputs") or k in ("candidateOnly", "baselineOnly")),
        "allOutputsBitwiseEqual": set(metrics) == set(expected_metrics) and all(
            metrics[key]["observations"] == counts.get(role + ".equalInputs", 0) > 0
            and metrics[key]["bitwiseDifferent"] == 0 for key, role in expected_metrics.items()),
        "sameOutputTrace": complete_trace(left["outputTraceSha256"]) and left["outputTraceSha256"] == right["outputTraceSha256"],
        "sameEndpointRecords": left["endpoints"] == right["endpoints"],
        "sameArgmaxTrace": bool(re.fullmatch("[0-9a-f]{64}", left["argmaxSequenceSha256"])) and left["argmaxSequenceSha256"] == right["argmaxSequenceSha256"],
        "sameFinalStopTokens": (left["tokenCountAtFinalStop"], left["finalStopTokenSha256"]) ==
                              (right["tokenCountAtFinalStop"], right["finalStopTokenSha256"]),
    }
    passed = all(all(group.values()) for group in (prepared_checks, speech_checks, zchecks))
    identity = read_json(evidence / "verified-tools.json")["build"]["artifactIdentity"]
    conclusion = "本用例逐位相同" if passed else "本用例未满足逐位相同条件"
    if identity == "IDENTICAL_ARTIFACT":
        conclusion += "；两份库逐字相同，需解释构建身份，不能据此确认候选差异"
    return {"allFixedCasesBitwiseEqual": passed, "artifactIdentity": identity,
            "distinctBuildComparisonPassed": passed and identity == "DISTINCT_ARTIFACTS", "conclusion": conclusion,
            "prepared": prepared_checks, "speech": speech_checks, "zipformer": zchecks,
            "testedScope": "固定主机 CPU 库与这些输入，未覆盖 Android 设备或其他模型输入"}


def session_logs(stage):
    if stage == "zipformer":
        return {f"{side}-{role}.stderr.txt": (side, role)
                for side in ("baseline", "candidate") for role in ("encoder", "decoder", "joiner")}
    groups = {"prepared": ("bge", "smartTurn"), "speech": ("silero", "smart")}.get(stage, ())
    return {f"{role}-{key}-stderr.txt": (side, role)
            for key, side in (("left", "baseline"), ("right", "candidate")) for role in groups}


def model_progress(stage, journal):
    logs = session_logs(stage)
    rows = {key: {"side": side, "model": model, "state": "NOT_RUN", "completedRuns": 0}
            for key, (side, model) in logs.items()}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            row = rows[event["log"]]
            row["completedRuns"] = event["completedRuns"]
            if row["state"] not in ("RUN_FAILED", "SESSION_FAILED", "EXIT_FAILED"):
                row["state"] = event["state"]
    return rows


def diagnostic_tail(path):
    if not path.is_file():
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        start = max(0, f.tell() - 16384)
        f.seek(start)
        if start:
            f.readline()
        data = f.read()
    # Only fixed C++ ORT stderr or Python error text. Never ingest stdout,
    # tensor manifests, input/output files or numeric array representations.
    lines = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line)
        line = "".join(c for c in line if c.isprintable()).strip()
        if not line or re.search(r"(?:[-+]?\d+(?:\.\d+)?[ ,;]+){12}|array\(\[|[A-Za-z0-9+/=]{180,}", line):
            continue
        lines.append(line[:1000])
    return "\n".join(lines[-12:])[-4000:]


def run(args, actions):
    work = args.work
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    priv = work / "private"
    evidence = work / "evidence"
    priv.mkdir(mode=0o700)
    evidence.mkdir()
    (priv / "tmp").mkdir(mode=0o700)
    (priv / "classes").mkdir()
    log = {name: {"status": "NOT_RUN"} for name in actions}
    for stage in actions:
        if session_logs(stage):
            log[stage]["modelSessions"] = model_progress(stage, priv / f"{stage}.events")
    status = {"started": now(), "stages": log, "firstError": None}
    status_path = evidence / "status.json"
    write_json(status_path, status)
    env = {**os.environ, "TMPDIR": str(priv / "tmp"), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONOPTIMIZE": "0", "ORT_LOAD_CONFIG_FROM_MODEL": "0"}
    for name, command in actions.items():
        entry = log[name]
        entry.update(status="RUNNING", started=now())
        write_json(status_path, status)
        try:
            if name == "verify-tools":
                write_json(evidence / "verified-tools.json", verify_tools(args))
            elif name == "aggregate":
                result = aggregate(evidence)
                write_json(evidence / "aggregate.json", result)
                if not result["distinctBuildComparisonPassed"]:
                    raise ValueError("数值对照完成，详见 aggregate.json 和三份 result.json")
            else:
                # Keep compiler diagnostics and any native stdout/stderr private.
                # Move only parsed UTF-8 JSON to the exportable evidence tree.
                stdout = priv / f"{name}.stdout"
                stderr = priv / f"{name}.stderr"
                with stdout.open("wb") as out, stderr.open("wb") as err:
                    journal = priv / f"{name}.events"
                    child_env = dict(env)
                    child_env.pop("ORT_RESEARCH_PROGRESS_FILE", None)
                    if session_logs(name):
                        child_env["ORT_RESEARCH_PROGRESS_FILE"] = str(journal)
                    proc = subprocess.run(command, env=child_env, stdout=out, stderr=err)
                if session_logs(name):
                    entry["modelSessions"] = model_progress(name, journal)
                entry["exitCode"] = proc.returncode
                if proc.returncode:
                    logs = entry.get("modelSessions", {})
                    native_errors = {key: diagnostic_tail(priv / name / key) for key, state in logs.items()
                                     if state["state"] != "NOT_RUN" and state["state"] != "SCOPE_FINISHED"}
                    entry["nativeDiagnostics"] = {k: v for k, v in native_errors.items() if v}
                    diagnostic = diagnostic_tail(stderr)
                    failed = ", ".join(k for k, v in logs.items() if v["state"].endswith("FAILED"))
                    raise RuntimeError(f"{name} exit {proc.returncode} {failed}: {diagnostic}")
                if name in ("verify-inputs", "fixture-cases", "public-wav-cases"):
                    write_json(evidence / f"{name}.json", read_json(stdout))
                elif name in ("prepared", "speech", "zipformer"):
                    write_json(evidence / name / "result.json", read_json(priv / name / "result.json"))
            entry.update(status="PASS", finished=now())
        except (Exception, KeyboardInterrupt) as exc:
            if session_logs(name):
                entry["modelSessions"] = model_progress(name, priv / f"{name}.events")
            entry.update(status="FAIL", finished=now())
            status["firstError"] = {"stage": name, "type": type(exc).__name__, "message": str(exc)}
            if entry.get("nativeDiagnostics"):
                status["firstError"]["nativeDiagnostics"] = entry["nativeDiagnostics"]
            status["finished"] = now()
            write_json(status_path, status)
            print(json.dumps(status["firstError"], ensure_ascii=False), file=sys.stderr)
            return 1
        write_json(status_path, status)
    status["finished"] = now()
    write_json(status_path, status)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("inputs", "kotlin-jars", "json-jar", "baseline-library", "candidate-library", "build-evidence", "work"):
        parser.add_argument("--" + key, required=True, type=lambda s: Path(s).resolve())
    parser.add_argument("--plan", action="store_true", help="只显示有序命令和内置校验，不运行或创建工作目录")
    args = parser.parse_args()
    actions = stages(args)
    if args.plan:
        print(json.dumps({"work": str(args.work), "stages": [
            {"name": n, "argv": a} if a is not None else {"name": n, "inProcess": True}
            for n, a in actions.items()]}, indent=2, ensure_ascii=False))
        return 0
    if os.path.lexists(args.work):
        parser.error("--work 必须为全新目录")
    return run(args, actions)


if __name__ == "__main__":
    sys.exit(main())
