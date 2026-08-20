# AuraDE local assistant integration

This page describes a direction, not a promise that a particular provider or
model ships in the base image.

## Goals

- Keep the base desktop useful with no assistant installed.
- Prefer local processing for private notes and documents.
- Make network use explicit and easy to disable.
- Keep the interface stable while providers change.
- Work on low-memory hardware by failing clearly instead of swapping forever.

## Provider boundary

The desktop should talk to a small local service with a documented request and
response format. Provider packages belong outside the base profile. The service
must expose health, model availability, memory use, and a stop action.

No provider may read a user's files, microphone, clipboard, or browser data by
default. Access needs a visible permission and a short explanation.

## Privacy and safety

Credentials belong in the user's secret store or the provider's documented
configuration, never in source, package metadata, logs, or bug reports. The
installer and desktop must continue to work when credentials are absent.

## First useful slice

The first release-quality slice is a local health page, an explicit provider
toggle, one small text request, cancellation, and a redacted diagnostic status.
More ambitious features can follow after resource and privacy tests exist.
