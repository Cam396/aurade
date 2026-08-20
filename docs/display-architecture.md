# AuraDE display architecture

Status: accepted. Weston with the kiosk shell is the supported packaged
default. Direct DRM remains a future option, and cage is not part of the
supported daily-driver path.

## Why Weston is the default

Ash runs as the main client of a Wayland compositor. That gives AuraDE a
stable seat, a clear restart boundary, and a useful fallback when the browser
session crashes. It also keeps the display and session behavior understandable
on generic Linux hardware.

The extra compositor has a cost in memory and latency. Those costs are known
and measurable, and they are preferable to making the whole seat disappear
when the browser or a graphics path fails.

## Why not direct DRM yet

Direct DRM could reduce one layer and improve the best-case path. It still
needs a reliable seat handoff, crash recovery, display hotplug behavior, and
coverage across Intel, AMD, and less common graphics hardware. It will become
the default only after those gates are real on hardware.

## Consequences

- The session package depends on Weston.
- Renderer fallback remains part of the live installer and session startup.
- Display hotplug and restart behavior should be improved in the supported
  path before a compositor change is considered.
- Experimental display modes must never be presented as release support.
