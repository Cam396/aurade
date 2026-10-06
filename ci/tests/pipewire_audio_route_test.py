#!/usr/bin/env python3
"""Execute the shipped route policy and check its adapter wiring separately."""

from pathlib import Path
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "chromeos/ash/components/dbus/audio/"
HEADER = PREFIX + "pipewire_audio_route.h"
CLIENT = PREFIX + "pipewire_cras_audio_client.cc"
PATCH = "0137-volume-and-mute-follow-the-sound-card.patch"


def run(command, **kwargs):
    kwargs.setdefault("timeout", 60)
    return subprocess.run(command, text=True, capture_output=True, **kwargs)


def checked(command, **kwargs):
    result = run(command, **kwargs)
    if result.returncode:
        raise RuntimeError(f"command failed: {shlex.join(map(str, command))}\n"
                           f"{result.stdout}{result.stderr}\nEXIT={result.returncode}")
    return result.stdout


def body(text, name):
    start = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*(?:const\s*)?"
                      r"(?:EXCLUSIVE_LOCKS_REQUIRED\(lock\)\s*)?\{", text)
    if not start:
        raise ValueError(f"missing function: {name}")
    depth = 1
    pos = start.end()
    while pos < len(text) and depth:
        depth += (text[pos] == "{") - (text[pos] == "}")
        pos += 1
    if depth:
        raise ValueError(f"unclosed function: {name}")
    return text[start.end():pos - 1]


def code(text):
    return re.sub(r"\s+", " ", re.sub(r"//[^\n]*", "", text)).strip()


def wiring_failures(client, patch, series):
    failures = []

    def check(name, valid):
        if not valid:
            failures.append(name)

    check("series", series.count(PATCH) == 1)
    check("target", '+    "pipewire_audio_route.h",' in patch)
    check("device binding", "PW_TYPE_INTERFACE_Device" in body(client, "OnRegistryGlobal")
          and "PipeWireDeviceAddListener(proxy, &stored->listener, &kDeviceEvents, stored)"
          in code(body(client, "OnRegistryGlobal")))
    identity = code(body(client, "RefreshNodeIdentityLocked"))
    check("global device mapping", "const std::string device_id = DictString(props, PW_KEY_DEVICE_ID);" in identity
          and "node.device_id = pipewire_audio::ParseId(device_id);" in identity)
    check("profile device mapping", 'const std::string profile_device = DictString(props, "card.profile.device");' in identity
          and "node.profile_device = pipewire_audio::ParseId(profile_device);" in identity)
    # PipeWire sends a node's properties only when they change. An update
    # without them must not cut the node off from its sound card.
    check("partial update", "if (!device_id.empty()) {" in identity and
          "if (!profile_device.empty()) {" in identity)
    info = code(body(client, "OnDeviceInfo"))
    check("parameter invalidation", "PW_DEVICE_CHANGE_MASK_PARAMS" in info and
          "SPA_PARAM_INFO_READ" in info and "device->routes.Begin(request)" in info)
    check("route enumeration", "PipeWireDeviceEnumRoutes(device->device.get(), request)" in info and
          "PipeWireCoreSync(state->core.get(), PW_ID_CORE, 0)" in info)
    # PipeWire tags the replies with the sequence the enumeration returns,
    # not the one passed in; matched against the passed one, every route was
    # dropped and the volume went to the software gain.
    check("returned sequence", "device->request_seq = enumerated;" in info and
          "device->routes.Begin(enumerated)" in info)
    # Only the core's own error ends the client; one refused request does not.
    check("core error scope", "if (id == PW_ID_CORE)" in code(body(client, "OnCoreError")))
    check("transaction completion", "device.sync_seq == seq" in body(client, "OnCoreDone") and
          "device.routes.Complete(device.request_seq)" in body(client, "OnCoreDone"))
    check("parameter callback", "device->routes.Add(seq, param)" in body(client, "OnDeviceParam"))
    removal = body(client, "OnRegistryGlobalRemove")
    check("listener lifetime", removal.find("spa_hook_remove(&device->second.listener)") >= 0 and
          removal.find("spa_hook_remove(&device->second.listener)") < removal.find("state->devices.erase(device)"))
    check("effective state", "pipewire_audio::ReadLevel(" in body(client, "ApplyEffectivePropsLocked"))
    setter = code(body(client, "SetNodeProps"))
    check("transition write guard", "device_iter->second.routes.loading() || device_iter->second.query_failed" in setter
          and "if (!node || routes_loading)" in setter)
    check("query error blocks writes", "device->query_failed = sync < 0;" in info)
    check("asynchronous error blocks writes", "if (state_->core_failed)" in setter)
    check("physical writer", "PipeWireDeviceSetRoute(device, pod)" in setter and
          "PipeWireNodeSetParam(node, SPA_PARAM_Props, 0, pod)" in setter and
          "pipewire_audio::WriteProps(" in setter)
    for name in ("SetOutputNodeVolume", "SetOutputUserMute", "SetInputNodeGain", "SetInputMute"):
        source = code(body(client, name))
        check(name + " confirmation", "SetNodeProps(" in source and
              not any(token in source for token in (".volume =", ".muted =", "PostOutput", "PostInput", "volume_state.")))
    return failures


def replace(text, old, new, function=None):
    selected = body(text, function) if function else text
    if selected.count(old) != 1:
        raise ValueError(f"mutation anchor count {selected.count(old)}: {function}: {old}")
    changed = selected.replace(old, new, 1)
    return text.replace(selected, changed, 1) if function else changed


# Each row changes production behavior. A compile failure is not accepted as
# proof that the behavioral assertion catches a regression.
MUTATIONS = [
    ("zero id", "ParseId", "return result;", "return result == 0 ? SPA_ID_INVALID : result;"),
    ("numeric id tail", "ParseId", "parsed.ptr != end", "false"),
    ("cubic read", "PercentFromVolume", "std::cbrt", "std::sqrt"),
    ("cubic write", "VolumeFromPercent", "value * value * value", "value"),
    ("write clamp", "VolumeFromPercent", "std::clamp(percent, 0, 100)", "percent"),
    ("read clamp", "PercentFromVolume", "std::min(volume, 1.0f)", "volume"),
    ("props type", "ReadProps", "SPA_POD_OBJECT_TYPE(pod) != SPA_TYPE_OBJECT_Props", "false"),
    ("props size", "ReadProps", "pod->size > kMaxPodBytes", "false"),
    ("mute type", "ReadProps", "spa_pod_get_bool(&prop->value, &muted) < 0", "(spa_pod_get_bool(&prop->value, &muted), false)"),
    ("array type", "ReadProps", "SPA_POD_ARRAY_VALUE_TYPE(&prop->value) != SPA_TYPE_Float", "false"),
    ("element size", "ReadProps", "SPA_POD_ARRAY_VALUE_SIZE(&prop->value) != sizeof(float)", "false"),
    ("empty channels", "ReadProps", "count == 0", "false"),
    ("channel bound", "ReadProps", "count > kMaxChannels", "count > kMaxChannels + 1"),
    ("finite channels", "ReadProps", "!std::isfinite(volume)", "false"),
    ("negative channels", "ReadProps", "volume < 0.0f", "false"),
    ("props assignment", "ReadProps", "*output = std::move(next);", "*output = Props{};"),
    ("mute merge", "MergeProps", "target->muted = update.muted;", "target->muted = false;"),
    ("volume merge", "MergeProps", "target->volumes = update.volumes;", "target->volumes = {1.0f};"),
    ("route precedence", "ReadLevel", "route ? route->props : node", "route ? node : node"),
    ("channel zero", "ReadLevel", "props.volumes.front()", "props.volumes.back()"),
    ("mute state", "ReadLevel", "previous.muted = *props.muted;", "previous.muted = false;"),
    ("missing fields", "ReadLevel", "return previous;", "if (!route && node.volumes.empty()) previous.volume = 100; return previous;"),
    ("route index bound", "ReadRoute", "next.index < 0", "false"),
    ("profile bound", "ReadRoute", "next.profile_device < 0", "false"),
    ("direction type", "ReadRoute", "spa_pod_get_id(&direction->value, &next.direction) < 0", "(spa_pod_get_id(&direction->value, &next.direction), false)"),
    ("optional direction", "ReadRoute", "Route next;", "Route next; next.direction = SPA_DIRECTION_OUTPUT;"),
    ("route completeness", "ReadRoute", "!next.props.muted.has_value()", "false"),
    ("stale enumeration", "Add", "sequence != sequence_", "false"),
    ("closed enumeration", "Add", "!loading_", "false"),
    ("stale completion", "Complete", "sequence != sequence_", "false"),
    ("route limit", "Add", "pending_.size() >= kMaxRoutes", "pending_.size() > kMaxRoutes"),
    ("overflow publication", "Complete", "overflow_ ? std::vector<Route>() : std::move(pending_)", "std::move(pending_)"),
    ("empty snapshot", "Complete", "current_ =", "if (!pending_.empty()) current_ ="),
    ("device removal", "Clear", "current_.clear();", ";"),
    ("global isolation", "Find", "global_device != global_device_", "(global_device != global_device_ && false)"),
    ("profile isolation", "Find", "static_cast<uint32_t>(route.profile_device) == profile_device", "static_cast<uint32_t>(route.index) == profile_device"),
    ("direction isolation", "Find", "route.direction == direction", "true"),
    ("input selection", "Find", "route.direction == direction", "(route.direction == direction && direction == SPA_DIRECTION_OUTPUT)"),
    ("route write index", "WriteProps", "SPA_POD_Int(route->index)", "SPA_POD_Int(route->profile_device)"),
    ("route write device", "WriteProps", "SPA_POD_Int(route->profile_device)", "SPA_POD_Int(route->index)"),
    ("route persistence", "WriteProps", "SPA_POD_Bool(true)", "SPA_POD_Bool(false)"),
    ("mute value", "WriteProps", "spa_pod_builder_bool(&builder, *mute)", "spa_pod_builder_bool(&builder, false)"),
    ("write channel bound", "WriteProps", "channels > kMaxChannels", "channels > kMaxChannels + 1"),
    ("empty write", "WriteProps", "(!volume.has_value() && !mute.has_value())", "false"),
    ("write routing", "WriteProps", "route ? write_route(pod) : write_node(pod)", "route ? write_node(pod) : write_node(pod)"),
    ("write failure", "WriteProps", ") >= 0;", ") >= -100;"),
]


def main():
    audit = sys.argv[1:] == ["--mutation-audit"]
    if sys.argv[1:] and not audit:
        raise ValueError("usage: pipewire-audio-route-test.sh [--mutation-audit]")
    series = (ROOT / "patches/SERIES").read_text().splitlines()
    original_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in [ROOT / "patches/SERIES", ROOT / "patches" / PATCH]}
    patch = (ROOT / "patches" / PATCH).read_text()
    with tempfile.TemporaryDirectory(prefix="audio-route-") as directory:
        scratch = Path(directory)
        checked(["git", "init", "-q", str(scratch)])
        for name in series:
            if not name or name.startswith("#"):
                continue
            candidate = ROOT / "patches" / name
            contents = candidate.read_text()
            if any("+++ b/" + path in contents for path in (HEADER, CLIENT)):
                checked(["git", "apply", "--include=" + HEADER,
                         "--include=" + CLIENT, str(candidate)], cwd=scratch)
        header_path = scratch / HEADER
        header = header_path.read_text()
        client = (scratch / CLIENT).read_text()
        failures = wiring_failures(client, patch, series)
        if failures:
            raise ValueError("adapter wiring failed: " + ", ".join(failures))
        compiler = shlex.split(os.environ.get("CXX", "clang++"))
        flags = shlex.split(checked(["pkg-config", "--cflags", "libspa-0.2"]))
        command = compiler + ["-std=c++20", "-O0", "-g", "-Wall", "-Wextra", "-Werror",
                              "-Wno-unused-parameter", "-fsanitize=address,undefined",
                              "-fno-omit-frame-pointer", "-I" + str(scratch)] + flags + [
                              str(ROOT / "ci/tests/pipewire-audio-route-test.cc"),
                              "-o", str(scratch / "test")]

        def test(source):
            header_path.write_text(source)
            checked(command, timeout=300)
            # Symbolization is not the safety check. Keep both sanitizers
            # enabled, but do not launch an external symbolizer for deliberate
            # faults: a stuck symbolizer must not stall the mutation audit.
            environment = dict(os.environ, ASAN_OPTIONS="symbolize=0:halt_on_error=1",
                               UBSAN_OPTIONS="print_stacktrace=0:halt_on_error=1")
            return run([str(scratch / "test")], env=environment)

        result = test(header)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        print(result.stdout, end="")
        print("audio route adapter wiring: PASS (source checks, not a Chromium link)")
        if audit:
            print("mutation | gate | result")
            for name, function, old, new in MUTATIONS:
                changed = replace(header, old, new, function)
                result = test(changed)
                if not result.returncode:
                    raise RuntimeError("NOT CAUGHT: " + name)
                if not any(marker in result.stderr for marker in (
                        "FAIL: ", "ERROR: AddressSanitizer:", "runtime error:")):
                    raise RuntimeError("mutation stopped without an assertion or sanitizer failure: " + name)
                print(f"{name} | behavior | caught")
            wiring_mutations = [
                ("series", "series", PATCH, "removed.patch"),
                ("target", "patch", '+    "pipewire_audio_route.h",', '+    "missing.h",'),
                ("device binding", "client", "PipeWireDeviceAddListener(proxy,", "MissingListener(proxy,"),
                ("global device mapping", "client", "node.device_id =", "node.missing_device ="),
                ("profile device mapping", "client", "node.profile_device =", "node.missing_profile ="),
                ("parameter invalidation", "client", "PW_DEVICE_CHANGE_MASK_PARAMS", "PW_DEVICE_CHANGE_MASK_PROPS"),
                ("route enumeration", "client", "PipeWireDeviceEnumRoutes(device->device.get(), request)", "OtherEnum(device->device.get(), request)"),
                ("partial update", "client", "if (!device_id.empty()) {", "if (true) {"),
                ("returned sequence", "client", "device->routes.Begin(enumerated)", "device->routes.Begin(request)"),
                ("core error scope", "client", "if (id == PW_ID_CORE) {", "if (true) {"),
                ("transaction completion", "client", "device.sync_seq == seq", "true"),
                ("parameter callback", "client", "device->routes.Add(seq, param)", "device->routes.Add(0, param)"),
                ("listener lifetime", "client", "spa_hook_remove(&device->second.listener);", ";"),
                ("effective state", "client", "pipewire_audio::ReadLevel(", "OtherLevel("),
                ("transition write guard", "client", "if (!node || routes_loading)", "if (!node)"),
                ("query error blocks writes", "client", "device->query_failed = sync < 0;", "device->query_failed = false;"),
                ("asynchronous error blocks writes", "client", "if (state_->core_failed)", "if (false)"),
                ("physical writer", "client", "PipeWireDeviceSetRoute(device, pod)", "OtherWriter(device, pod)"),
            ]
            for name, target, old, new in wiring_mutations:
                values = {"client": client, "patch": patch, "series": "\n".join(series)}
                values[target] = replace(values[target], old, new)
                failures = wiring_failures(values["client"], values["patch"], values["series"].splitlines())
                if name not in failures:
                    raise RuntimeError("wiring mutation NOT CAUGHT: " + name)
                print(f"{name} | adapter source | caught")
            for name in ("SetOutputNodeVolume", "SetOutputUserMute", "SetInputNodeGain", "SetInputMute"):
                selected = body(client, name)
                changed = client.replace(selected, selected + "\nPostOutputMuteChanged(false);\n", 1)
                if name + " confirmation" not in wiring_failures(changed, patch, series):
                    raise RuntimeError("confirmation mutation NOT CAUGHT: " + name)
                print(f"{name} confirmation | adapter source | caught")
            if test(header).returncode:
                raise RuntimeError("baseline did not recover after mutations")
            print(f"audio route mutation audit: PASS ({len(MUTATIONS)} behavioral, {len(wiring_mutations) + 4} adapter-source mutations)")
    for name, digest in original_hashes.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("source changed during fixture: " + name)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("audio route test: " + str(error), file=sys.stderr)
        raise SystemExit(1)
