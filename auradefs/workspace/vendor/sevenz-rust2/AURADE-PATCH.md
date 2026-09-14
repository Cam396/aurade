# sevenz-rust2 0.19.4, carried here with one addition

This is the crates.io release of sevenz-rust2 0.19.4 (Apache-2.0, see
LICENSE), without its tests and examples, plus one change in
`src/encoder_options.rs`:

- `Lzma2Options::set_nice_len` and `Lzma2Options::set_chunk_size`, and the
  readers `dictionary_size`, `nice_len`, `threads` and `chunk_size`.
- `Coder::properties` in `src/block.rs`, so an archive's LZMA2 dictionary
  can be read back from its header.

The release exposes the LZMA2 dictionary size and the thread count but not
the match finder's nice length, which 7-Zip calls the word size. The Create
archive dialog in Files offers all three, so the daemon needs all three to
reach the codec. Everything else is byte for byte the release.

The workspace `Cargo.toml` points `sevenz-rust2` here through
`[patch.crates-io]`. Drop the patch once a release carries a setter for the
nice length.
