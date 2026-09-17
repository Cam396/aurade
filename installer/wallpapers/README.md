# Wallpapers

Twenty-eight PNG photographs used by the installer. They are free to use and
do not require attribution.

The files are grouped by name:

- `place-*` has a real location and caption.
- `quiet-*` has no location.
- `wild-*` covers weather and geology; some entries have locations.

## Use

The installer stages these files at
`/usr/local/share/aurade/wallpapers`. The installed desktop does not use this
set. Images are 1376x768 PNGs so the installer can draw them without resizing
the source files.

## Manifest

`manifest.tsv` is built from the image files and the hand-maintained metadata
in `titles.tsv`:

    installer/tools/wallpaper-manifest.py installer/wallpapers \
      --titles installer/wallpapers/titles.tsv \
      --out installer/wallpapers/manifest.tsv

The tool checks dimensions, colour count, luminance range, and metadata. Update
`titles.tsv`, then rebuild the manifest. Do not edit the manifest directly.

The catalog uses short captions and factual location notes. Entries without a
location have no time zone or location fact.
