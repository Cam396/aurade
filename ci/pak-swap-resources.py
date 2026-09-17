#!/usr/bin/env python3
"""Transplant resources from one .pak into another, offsets and all.

Why this exists: the Files app, and every other WebUI, is not in the chrome
binary. It is a handful of gzipped entries inside resources.pak, which is data
read by offset at runtime. So a change confined to TypeScript and HTML can
reach a machine by rewriting that one file, and never link chrome at all. On
this tree a full link is 43,084 edges and about six hours, which on this
hardware is also a thermal risk.

The safety rule here is not negotiable: resources.pak carries every WebUI on
the system, so a wrong offset is not one broken app, it is the whole desktop.
Every write is reparsed afterwards and the result must differ from the original
in exactly the resources that were asked for, with the alias table and the
order of every entry unchanged. Anything else exits non-zero and writes
nothing.

Resources present in the donor but absent from the target are reported and
skipped rather than inserted. Adding an id changes the resource count and the
ordering the reader binary searches, and a machine that renders without them
today is not made better by guessing.

Usage:
  pak-swap-resources.py TARGET DONOR OUTPUT [--ids 46750,46872] [--expect STR]
"""
import argparse
import gzip
import os
import struct
import sys

PAK_VERSION = 5
HEADER = "<IBBBBHH"
HEADER_SIZE = 12
ENTRY = "<HI"
ENTRY_SIZE = 6
ALIAS = "<HH"
ALIAS_SIZE = 4


def parse(path):
    data = open(path, "rb").read()
    version, = struct.unpack_from("<I", data, 0)
    if version != PAK_VERSION:
        raise SystemExit("%s is pak version %d, only %d is supported"
                         % (path, version, PAK_VERSION))
    encoding = data[4]
    count, alias_count = struct.unpack_from("<HH", data, 8)
    entries = [struct.unpack_from(ENTRY, data, HEADER_SIZE + i * ENTRY_SIZE)
               for i in range(count + 1)]
    alias_base = HEADER_SIZE + (count + 1) * ENTRY_SIZE
    aliases = [struct.unpack_from(ALIAS, data, alias_base + i * ALIAS_SIZE)
               for i in range(alias_count)]
    payloads = [(entries[i][0], data[entries[i][1]:entries[i + 1][1]])
                for i in range(count)]
    return encoding, aliases, payloads


def build(encoding, aliases, payloads):
    count, alias_count = len(payloads), len(aliases)
    out = struct.pack(HEADER, PAK_VERSION, encoding, 0, 0, 0, count, alias_count)
    offset = HEADER_SIZE + (count + 1) * ENTRY_SIZE + alias_count * ALIAS_SIZE
    table = b""
    for resource_id, blob in payloads:
        table += struct.pack(ENTRY, resource_id, offset)
        offset += len(blob)
    # The sentinel carries the end of the data, which is how the reader knows
    # how long the final resource is.
    table += struct.pack(ENTRY, 0, offset)
    alias_table = b"".join(struct.pack(ALIAS, a, b) for a, b in aliases)
    return out + table + alias_table + b"".join(blob for _, blob in payloads)


def decompress(blob):
    if blob[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(blob)
        except OSError:
            return blob
    return blob


def content_map(target, donor):
    """Work out which target id each donor id corresponds to.

    Resource ids are not stable between builds. Match resources by their bytes
    before applying replacements so a change in id numbering cannot swap the
    wrong entries.
    """
    by_bytes = {}
    for resource_id, blob in target.items():
        by_bytes.setdefault(blob, []).append(resource_id)

    mapping, deltas = {}, {}
    for resource_id, blob in donor.items():
        hits = by_bytes.get(blob, ())
        # Duplicate payloads are common (empty files, repeated licence headers)
        # and prove nothing about identity, so only unique matches count.
        if len(hits) == 1:
            mapping[resource_id] = hits[0]
            deltas[hits[0] - resource_id] = deltas.get(hits[0] - resource_id, 0) + 1

    if not deltas:
        raise SystemExit("no donor resource matches the target uniquely; "
                         "these paks have nothing in common")

    delta, agree = max(deltas.items(), key=lambda kv: kv[1])
    coverage = agree / float(len(mapping))
    print("  mapping: %d unique matches, %d agree on a shift of %+d (%.0f%%)"
          % (len(mapping), agree, delta, coverage * 100))
    if coverage < 0.90:
        raise SystemExit("the matched resources do not agree on a single shift "
                         "(%.0f%% agree); refusing to guess" % (coverage * 100))

    # A resource being changed has different bytes by definition, so it never
    # matches and has to be placed by that consensus.
    for resource_id in donor:
        mapping.setdefault(resource_id, resource_id + delta)
    return mapping, delta


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="the pak being rewritten")
    parser.add_argument("donor", help="the pak supplying new resource bytes")
    parser.add_argument("output", help="where to write the result")
    parser.add_argument("--ids", help="comma separated DONOR resource ids; "
                                      "default is every mapped id whose bytes differ")
    parser.add_argument("--map-by-content", action="store_true",
                        help="derive the donor to target id mapping from "
                             "matching payloads, for paks whose ids have drifted")
    parser.add_argument("--expect", action="append", default=[],
                        help="a string that must appear in the decompressed "
                             "output, as DONOR_ID:TEXT. Repeatable.")
    args = parser.parse_args()

    encoding, aliases, payloads = parse(args.target)
    _, _, donor_payloads = parse(args.donor)
    donor = dict(donor_payloads)
    target = dict(payloads)

    if args.map_by_content:
        mapping, _ = content_map(target, donor)
    else:
        mapping = {r: r for r in donor}
        # Same id mode is only meaningful when an id still means the same file.
        # Checking that here is the difference between a refusal and a desktop
        # that no longer boots: the verification further down counts how many
        # resources changed, which a wholesale misalignment passes happily.
        shared = [r for r in donor if r in target]
        # Below a couple of dozen shared ids the proportion says nothing: a
        # three resource fixture legitimately rewrites two of them. The signal
        # only means anything on a real pak, so it is only read there.
        if len(shared) >= 20:
            identical = sum(1 for r in shared if donor[r] == target[r])
            if identical < len(shared) * 0.5:
                raise SystemExit(
                    "only %d of %d shared ids hold identical bytes, so these "
                    "builds have drifted and an id no longer means the same "
                    "resource. Re-run with --map-by-content."
                    % (identical, len(shared)))

    placed = {d: t for d, t in mapping.items() if t in target}
    absent = sorted(d for d in donor if d not in placed)
    if absent:
        print("  skipped, no counterpart in the target: %s" % absent)

    if args.ids:
        wanted = sorted(int(x) for x in args.ids.split(","))
        for d in wanted:
            if d not in donor:
                raise SystemExit("resource %d is not in the donor" % d)
            if d not in placed:
                raise SystemExit("resource %d has no counterpart in the target" % d)
    else:
        wanted = sorted(d for d in placed if target[placed[d]] != donor[d])
    if not wanted:
        raise SystemExit("nothing to swap: no mapped resource differs")

    # Everything not being changed must already agree across the mapping. This
    # is what proves the mapping is real rather than merely self consistent.
    unchanged = [d for d in placed if d not in wanted]
    disagree = [d for d in unchanged if donor[d] != target[placed[d]]]
    if disagree:
        raise SystemExit("%d mapped resource(s) that are not being swapped do "
                         "not match across the mapping, so it is wrong: %s"
                         % (len(disagree), disagree[:8]))
    print("  mapping verified: %d untouched resource(s) identical across it"
          % len(unchanged))

    swap = {placed[d]: donor[d] for d in wanted}
    print("  swapping %d resource(s): %s"
          % (len(wanted), ["%d->%d" % (d, placed[d]) for d in wanted]))
    rewritten = [(r, swap.get(r, blob)) for r, blob in payloads]

    # Write somewhere else and rename only once every check has passed, so a
    # failure cannot leave a plausible looking pak at the name somebody is
    # about to install.
    tmp = args.output + ".partial"
    with open(tmp, "wb") as handle:
        handle.write(build(encoding, aliases, rewritten))
    try:
        encoding2, aliases2, payloads2 = parse(tmp)
        if encoding2 != encoding:
            raise SystemExit("the encoding changed")
        if aliases2 != aliases:
            raise SystemExit("the alias table changed")
        if [r for r, _ in payloads2] != [r for r, _ in payloads]:
            raise SystemExit("the resource order changed")
        differing = [r for (r, a), (_, b) in zip(payloads, payloads2) if a != b]
        if differing != sorted(swap):
            raise SystemExit("changed %s, expected exactly %s"
                             % (differing, sorted(swap)))
        print("  verified: %d resources, %d aliases, exactly %d changed"
              % (len(payloads2), len(aliases2), len(differing)))

        final = dict(payloads2)
        failures = 0
        for expectation in args.expect:
            donor_id, _, text = expectation.partition(":")
            resource_id = placed.get(int(donor_id), int(donor_id))
            blob = decompress(final.get(resource_id, b""))
            ok = text.encode("utf-8") in blob
            print("    %-16s %-40s %s" % ("%s->%s" % (donor_id, resource_id),
                                          text[:40],
                                          "present" if ok else "ABSENT"))
            failures += 0 if ok else 1
        if failures:
            raise SystemExit("%d expectation(s) not met" % failures)
    except BaseException:
        os.unlink(tmp)
        raise
    os.replace(tmp, args.output)
    print("  wrote %s" % args.output)


if __name__ == "__main__":
    sys.exit(main())
