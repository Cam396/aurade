// Route volume is tested without a display, a PipeWire server or Chromium.
// The fixture includes the exact helper from the patch, not a reimplementation.
#include "chromeos/ash/components/dbus/audio/pipewire_audio_route.h"

#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>

namespace pa = ash::pipewire_audio;

void Require(bool condition, const char* name) {
  if (!condition) {
    std::cerr << "FAIL: " << name << '\n';
    std::exit(1);
  }
}

struct Pod {
  alignas(8) std::array<uint8_t, 8192> bytes{};

  const spa_pod* Props(std::optional<bool> mute,
                       std::vector<float> values,
                       bool force_empty = false,
                       bool wrong_array = false) {
    spa_pod_builder builder =
        SPA_POD_BUILDER_INIT(bytes.data(), uint32_t{8192});
    spa_pod_frame frame;
    spa_pod_builder_push_object(&builder, &frame, SPA_TYPE_OBJECT_Props,
                                SPA_PARAM_Props);
    if (mute.has_value()) {
      spa_pod_builder_prop(&builder, SPA_PROP_mute, 0);
      spa_pod_builder_bool(&builder, *mute);
    }
    if (!values.empty() || force_empty) {
      spa_pod_builder_prop(&builder, SPA_PROP_channelVolumes, 0);
      spa_pod_builder_array(&builder, sizeof(float),
                            wrong_array ? SPA_TYPE_Int : SPA_TYPE_Float,
                            values.size(), values.data());
    }
    return static_cast<const spa_pod*>(spa_pod_builder_pop(&builder, &frame));
  }

  const spa_pod* Route(int index,
                       int device,
                       uint32_t direction = SPA_DIRECTION_OUTPUT,
                       bool full = true) {
    Pod props;
    const auto* nested = props.Props(full ? std::optional(false) : std::nullopt,
                                     {0.064f, 0.125f});
    spa_pod_builder builder =
        SPA_POD_BUILDER_INIT(bytes.data(), uint32_t{8192});
    return static_cast<const spa_pod*>(spa_pod_builder_add_object(
        &builder, SPA_TYPE_OBJECT_ParamRoute, SPA_PARAM_Route,
        SPA_PARAM_ROUTE_index, SPA_POD_Int(index), SPA_PARAM_ROUTE_device,
        SPA_POD_Int(device), SPA_PARAM_ROUTE_direction, SPA_POD_Id(direction),
        SPA_PARAM_ROUTE_props, SPA_POD_Pod(nested)));
  }
};

void ScaleAndIds() {
  Require(pa::ParseId("0") == 0 && pa::ParseId("42") == 42,
          "zero is a valid id");
  for (auto text : {"", "-1", "+1", "2x", " 2", "4294967296"}) {
    Require(pa::ParseId(text) == SPA_ID_INVALID, "invalid id");
  }
  Require(pa::PercentFromVolume(0.064f) == 40, "cubic read");
  Require(std::abs(pa::VolumeFromPercent(40) - 0.064f) < 0.00001f,
          "cubic write");
  for (int percent : {0, 1, 25, 50, 75, 100}) {
    Require(pa::PercentFromVolume(pa::VolumeFromPercent(percent)) == percent,
            "scale round trip");
  }
  Require(pa::VolumeFromPercent(-50) == 0 && pa::VolumeFromPercent(150) == 1,
          "write clamp");
  Require(pa::PercentFromVolume(std::numeric_limits<float>::max()) == 100,
          "read clamp before round");
  Require(
      pa::PercentFromVolume(-1) == 0 &&
          pa::PercentFromVolume(std::numeric_limits<float>::quiet_NaN()) == 0,
      "invalid scalar");
}

void Properties() {
  Pod pod;
  pa::Props state;
  Require(pa::ReadProps(pod.Props(false, {0.064f, 0.125f}), &state),
          "read props");
  Require(state.muted == false &&
              state.volumes == std::vector<float>({0.064f, 0.125f}),
          "exact channel data");
  pa::Props update;
  Require(pa::ReadProps(pod.Props(true, {}), &update), "mute-only parse");
  pa::MergeProps(update, &state);
  Require(state.muted == true && state.volumes.front() == 0.064f,
          "mute-only merge");
  Require(pa::ReadProps(pod.Props(std::nullopt, {0.125f}), &update),
          "volume-only parse");
  pa::MergeProps(update, &state);
  Require(state.muted == true && state.volumes.front() == 0.125f,
          "volume-only merge");
  auto level = pa::ReadLevel(nullptr, {false, {0.064f, 1.0f}}, {90, true});
  Require(level.volume == 40 && !level.muted, "channel zero, not average");
  level = pa::ReadLevel(nullptr, {}, {73, true});
  Require(level.volume == 73 && level.muted, "missing fields preserve state");
  pa::Route route{71, 0, SPA_DIRECTION_OUTPUT, {true, {0.125f, 0.064f}}};
  level = pa::ReadLevel(&route, {false, {1.0f, 1.0f}}, {});
  Require(level.volume == 50 && level.muted, "route state wins");
}

void InvalidProperties() {
  Pod pod;
  pa::Props output{true, {0.125f}};
  Require(!pa::ReadProps(nullptr, &output), "null props");
  spa_pod not_object = {0, SPA_TYPE_Int};
  Require(!pa::ReadProps(&not_object, &output), "nonobject props");
  Require(!pa::ReadProps(pod.Route(3, 0), &output), "wrong object type");
  Require(!pa::ReadProps(pod.Props(false, {}, true), &output),
          "empty channel array");
  Require(!pa::ReadProps(pod.Props(false, {1}, false, true), &output),
          "wrong channel type");
  Require(!pa::ReadProps(pod.Props(false, std::vector<float>(65, 1)), &output),
          "channel limit");
  for (float value : {-0.1f, std::numeric_limits<float>::infinity(),
                      std::numeric_limits<float>::quiet_NaN()}) {
    Require(!pa::ReadProps(pod.Props(false, {0.1f, value}), &output),
            "invalid channel value");
  }
  Require(
      output.muted == true && output.volumes == std::vector<float>({0.125f}),
      "invalid input is atomic");
  auto* bad = const_cast<spa_pod*>(pod.Props(false, {1.0f}));
  bad->size = pa::kMaxPodBytes + 1;
  Require(!pa::ReadProps(bad, &output), "pod size limit");
  bad = const_cast<spa_pod*>(pod.Props(false, {1.0f}));
  auto* prop =
      const_cast<spa_pod_prop*>(spa_pod_find_prop(bad, nullptr, SPA_PROP_mute));
  prop->value.type = SPA_TYPE_Int;
  Require(!pa::ReadProps(bad, &output), "wrong mute type");
  bad = const_cast<spa_pod*>(pod.Props(false, {1.0f}));
  prop = const_cast<spa_pod_prop*>(
      spa_pod_find_prop(bad, nullptr, SPA_PROP_channelVolumes));
  reinterpret_cast<spa_pod_array*>(&prop->value)->body.child.size = 8;
  Require(!pa::ReadProps(bad, &output), "wrong channel element size");
  Require(pa::ReadProps(pod.Props(false, std::vector<float>(64, 1)), &output) &&
              output.volumes.size() == 64,
          "maximum channel array");
}

void Routes() {
  Pod pod;
  pa::Route route;
  Require(pa::ReadRoute(pod.Route(71, 0), &route), "route parse");
  Require(route.index == 71 && route.profile_device == 0 &&
              route.direction == SPA_DIRECTION_OUTPUT,
          "three route selectors");
  Require(!pa::ReadRoute(pod.Route(-1, 0), &route), "negative route index");
  Require(!pa::ReadRoute(pod.Route(71, -1), &route), "negative profile device");
  Require(!pa::ReadRoute(pod.Route(71, 0, 9), &route), "invalid direction");
  auto* bad = const_cast<spa_pod*>(pod.Route(71, 0));
  auto* direction = const_cast<spa_pod_prop*>(
      spa_pod_find_prop(bad, nullptr, SPA_PARAM_ROUTE_direction));
  direction->value.type = SPA_TYPE_Int;
  Require(!pa::ReadRoute(bad, &route), "wrong direction type");
  Require(!pa::ReadRoute(pod.Route(71, 0, SPA_DIRECTION_OUTPUT, false), &route),
          "incomplete route props");
  Require(!pa::ReadRoute(pod.Props(false, {1}), &route),
          "props is not a route");
  bad = const_cast<spa_pod*>(pod.Route(71, 0));
  direction = const_cast<spa_pod_prop*>(
      spa_pod_find_prop(bad, nullptr, SPA_PARAM_ROUTE_direction));
  direction->key = SPA_PARAM_ROUTE_info;
  Require(pa::ReadRoute(bad, &route) && route.direction == SPA_ID_INVALID,
          "missing direction stays optional");

  pa::RouteSnapshot snapshot(42);
  snapshot.Begin(1);
  Require(snapshot.loading() && !snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT),
          "snapshot starts unpublished");
  Require(!snapshot.Add(0, pod.Route(9, 0)), "stale enumeration ignored");
  Require(snapshot.Add(1, pod.Route(71, 0)),
          "snapshot accepts current sequence");
  Require(!snapshot.Complete(0), "stale completion ignored");
  Require(snapshot.Complete(1) && !snapshot.loading(),
          "snapshot publishes at completion");
  const auto* selected = snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT);
  Require(selected && selected->index == 71,
          "profile device is not route index");
  Require(!snapshot.Find(43, 0, SPA_DIRECTION_OUTPUT),
          "global device isolation");
  Require(!snapshot.Find(42, 1, SPA_DIRECTION_OUTPUT),
          "profile device isolation");
  Require(!snapshot.Find(42, 0, SPA_DIRECTION_INPUT), "direction isolation");
  Require(!snapshot.Add(1, pod.Route(99, 0)),
          "completed batch rejects callbacks");

  snapshot.Begin(2);
  snapshot.Add(2, pod.Route(72, 0));
  snapshot.Begin(3);
  snapshot.Add(3, pod.Route(73, 0));
  Require(!snapshot.Complete(2), "superseded completion ignored");
  Require(snapshot.Complete(3) &&
              snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT)->index == 73,
          "latest snapshot replaces old routes");
  snapshot.Begin(4);
  snapshot.Complete(4);
  Require(!snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT),
          "empty batch removes route");

  snapshot.Begin(5);
  snapshot.Add(5, pod.Route(74, 0));
  snapshot.Complete(5);
  snapshot.Clear();
  Require(!snapshot.loading() && !snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT),
          "device removal invalidates route");
  snapshot.Begin(6);
  for (size_t i = 0; i < pa::kMaxRoutes; ++i) {
    Require(snapshot.Add(6, pod.Route(i, i)), "maximum route count");
  }
  Require(!snapshot.Add(6, pod.Route(1000, 1000)), "route limit");
  snapshot.Complete(6);
  Require(!snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT),
          "overflow cannot publish partial snapshot");
  snapshot.Begin(7);
  snapshot.Add(7, pod.Route(81, 0, SPA_DIRECTION_INPUT));
  snapshot.Complete(7);
  selected = snapshot.Find(42, 0, SPA_DIRECTION_INPUT);
  Require(selected && selected->index == 81 &&
              !snapshot.Find(42, 0, SPA_DIRECTION_OUTPUT),
          "input route remains selectable");
}

void Writes() {
  pa::Route route{71, 0, SPA_DIRECTION_OUTPUT, {false, {0.064f, 0.125f}}};
  int route_calls = 0;
  int node_calls = 0;
  bool check_mute_only = false;
  auto route_writer = [&](const spa_pod* pod) {
    ++route_calls;
    int index = -1, device = -1;
    bool save = false;
    const spa_pod* nested = nullptr;
    uint32_t id = SPA_PARAM_Route;
    Require(spa_pod_parse_object(
                pod, SPA_TYPE_OBJECT_ParamRoute, &id, SPA_PARAM_ROUTE_index,
                SPA_POD_Int(&index), SPA_PARAM_ROUTE_device,
                SPA_POD_Int(&device), SPA_PARAM_ROUTE_save, SPA_POD_Bool(&save),
                SPA_PARAM_ROUTE_props, SPA_POD_Pod(&nested)) >= 0,
            "write route object");
    Require(index == 71 && device == 0 && save,
            "write identity and persistence");
    pa::Props props;
    Require(pa::ReadProps(nested, &props), "write nested props");
    if (check_mute_only) {
      Require(props.muted == true && props.volumes.empty(),
              "mute does not rewrite volume");
    } else {
      Require(!props.muted.has_value() && props.volumes.size() == 2 &&
                  std::abs(props.volumes[0] - 0.064f) < 0.00001f &&
                  props.volumes[0] == props.volumes[1],
              "scalar writes equal cubic channels");
    }
    return 0;
  };
  auto node_writer = [&](const spa_pod* pod) {
    ++node_calls;
    pa::Props props;
    Require(pa::ReadProps(pod, &props) && props.muted == true,
            "node fallback is Props");
    return 0;
  };
  Require(
      pa::WriteProps(&route, 2, 40, std::nullopt, route_writer, node_writer),
      "route write success");
  Require(route_calls == 1 && node_calls == 0, "route prevents node write");
  check_mute_only = true;
  Require(
      pa::WriteProps(&route, 2, std::nullopt, true, route_writer, node_writer),
      "route mute success");
  Require(
      pa::WriteProps(nullptr, 2, std::nullopt, true, route_writer, node_writer),
      "node fallback success");
  Require(route_calls == 2 && node_calls == 1, "fallback writer isolation");
  for (uint32_t channels : {0u, 65u, UINT32_MAX}) {
    Require(
        !pa::WriteProps(&route, channels, 40, false, route_writer, node_writer),
        "invalid write channel count");
  }
  Require(route_calls == 2 && node_calls == 1,
          "invalid write never dispatches");
  Require(!pa::WriteProps(nullptr, 2, std::nullopt, std::nullopt, route_writer,
                          node_writer),
          "empty write rejected");
  auto reject = [](const spa_pod*) { return -5; };
  Require(!pa::WriteProps(&route, 2, 40, true, reject, reject),
          "route write failure");
  Require(!pa::WriteProps(nullptr, 2, 40, true, reject, reject),
          "node write failure");
  Require(route.props.muted == false && route.props.volumes[0] == 0.064f,
          "write does not fabricate confirmation");
}

int main() {
  ScaleAndIds();
  Properties();
  InvalidProperties();
  Routes();
  Writes();
  std::cout << "audio route behavior test: PASS\n";
}
