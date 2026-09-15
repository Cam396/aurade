#!/usr/bin/env python3
"""Put the Files page into resources.pak, in place of the SWA's own.

pak-swap-resources.py moves resources between two paks that came out of the
same build. This one puts files the builder wrote into a pak, which is how
the AuraDE Files page reaches chrome://file-manager without a chrome link:
main.html's slot gets files.html and the slot holding the page's script gets
files.js. A resource keeps the path it is served at, so the replacement page
has to point its script tag at that same path: on the 152 pak it is
foreground/js/main.js. Get that wrong and the page still renders, because the
markup and the stylesheet are inline, and is dead, because the script never
arrives. That is what --expect and the src check below are for.

Slots are found by content, never by id, because ids move between builds:
the resource holding `--find TEXT` must be exactly one, and it is replaced by
the bytes of FILE, gzipped the way grit stores them.

The safety rule is the swap tool's: resources.pak carries every WebUI on the
system, so the result is reparsed and must differ from the original in
exactly the resources named, with the alias table and every other entry
unchanged, or nothing is written.

Usage:
  pak-set-resources.py TARGET OUTPUT \\
      --set 'chrome://file-manager/init_globals.js=dist/files.html' \\
      --set 'auraDeExactTime=dist/files.js' \\
      --expect 'files.html:data-path="~"'
"""
import argparse
import gzip
import os
import re
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


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="the pak being rewritten")
    parser.add_argument("output", help="where to write the result")
    parser.add_argument("--set", action="append", default=[], metavar="TEXT=FILE",
                        help="replace the one resource whose content holds TEXT "
                             "with the bytes of FILE. Repeatable.")
    parser.add_argument("--expect", action="append", default=[], metavar="LEAF:TEXT",
                        help="TEXT must appear in the placed FILE named LEAF, "
                             "read back out of the written pak. Repeatable.")
    parser.add_argument("--raw", action="store_true",
                        help="store the bytes as they are rather than gzipped")
    parser.add_argument("--allow-new-paths", action="store_true",
                        help="do not require a replacement page's relative "
                             "script and stylesheet paths to be ones the page "
                             "it replaces already asked for")
    args = parser.parse_args()
    if not args.set:
        raise SystemExit("nothing to set")

    encoding, aliases, payloads = parse(args.target)
    plain = {rid: decompress(blob) for rid, blob in payloads}

    placed = {}
    for spec in args.set:
        if "=" not in spec:
            raise SystemExit("--set wants TEXT=FILE, got %r" % spec)
        text, path = spec.split("=", 1)
        needle = text.encode("utf-8")
        hits = [rid for rid, body in plain.items() if needle in body]
        if len(hits) != 1:
            raise SystemExit("%r is in %d resource(s), and must be in exactly one: %s"
                             % (text, len(hits), hits[:8]))
        rid = hits[0]
        if rid in placed:
            raise SystemExit("resource %d named twice" % rid)
        body = open(path, "rb").read()
        blob = body if args.raw else gzip.compress(body, mtime=0)
        placed[rid] = (os.path.basename(path), blob, body)
        print("  %s -> resource %d (%d bytes, was %d)"
              % (path, rid, len(body), len(plain[rid])))

    # A resource is served at the path the binary gives it, and nothing in
    # the pak says what that path is. So a replacement page can only safely
    # ask for paths the page it replaces already asked for: those are known
    # to resolve. A page whose script does not resolve still renders, because
    # its markup and stylesheet are inline, and does nothing at all, which
    # looks like success in a screenshot.
    if not args.allow_new_paths:
        for rid, (leaf, _, body) in placed.items():
            if not leaf.endswith((".html", ".htm")):
                continue
            was = plain[rid]
            try:
                old_text = was.decode("utf-8")
                new_text = body.decode("utf-8")
            except UnicodeDecodeError:
                continue
            ref = r"""(?:src|href)=["']([^"']+)["']"""
            #: A chrome://file-manager/x URL and a relative x are the same
            #: resource, and the page being replaced spells them both ways.
            def bare(u):
                u = u.split("#", 1)[0].split("?", 1)[0]
                host = "chrome://file-manager/"
                return u[len(host):] if u.startswith(host) else u
            known = {bare(u) for u in re.findall(ref, old_text)}
            for want in (bare(u) for u in re.findall(ref, new_text)):
                if not want or ":" in want.split("/", 1)[0]:
                    continue
                if want not in known:
                    raise SystemExit(
                        "%s asks for %r, which the page it replaces never "
                        "asked for, so it may not resolve; pass "
                        "--allow-new-paths only if you know it does"
                        % (leaf, want))

    rewritten = [(rid, placed[rid][1] if rid in placed else blob)
                 for rid, blob in payloads]
    result = build(encoding, aliases, rewritten)

    # Reparse what would be written and prove the difference is exactly the
    # resources placed, and nothing else moved.
    enc2, aliases2, payloads2 = parse_bytes(result)
    if enc2 != encoding or aliases2 != aliases:
        raise SystemExit("the header or the alias table changed; refusing to write")
    if [r for r, _ in payloads2] != [r for r, _ in payloads]:
        raise SystemExit("the resource order changed; refusing to write")
    changed = [r for (r, a), (_, b) in zip(payloads, payloads2) if a != b]
    if sorted(changed) != sorted(placed):
        raise SystemExit("changed %s but was asked to change %s; refusing to write"
                         % (sorted(changed), sorted(placed)))
    back = {rid: decompress(blob) for rid, blob in payloads2}
    for rid, (leaf, _, body) in placed.items():
        if back[rid] != body:
            raise SystemExit("%s did not come back out of the pak intact" % leaf)
    for spec in args.expect:
        if ":" not in spec:
            raise SystemExit("--expect wants LEAF:TEXT, got %r" % spec)
        leaf, text = spec.split(":", 1)
        rids = [rid for rid, (l, _, _) in placed.items() if l == leaf]
        if not rids:
            raise SystemExit("--expect names %r, which was not placed" % leaf)
        if text.encode("utf-8") not in back[rids[0]]:
            raise SystemExit("%r is not in the placed %s" % (text, leaf))
    with open(args.output, "wb") as fh:
        fh.write(result)
    print("  wrote %s: %d resources, %d placed, %d bytes"
          % (args.output, len(payloads2), len(placed), len(result)))


def parse_bytes(data):
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(data)
        name = fh.name
    try:
        return parse(name)
    finally:
        os.unlink(name)


if __name__ == "__main__":
    main()
