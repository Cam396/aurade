# shellcheck shell=bash
# Finding and reading the King James Version that ships on the image.
#
# The same three answers the graphical front end needs, in shell: which books
# are there, what is a book called, and what does one chapter say. The files
# are one book per markdown document, one verse per line prefixed with its
# number, `## Chapter N` between chapters. `installer/bible/README.md` says why
# that shape and not another, and the short version is that it means neither
# front end needs a markdown engine, because neither front end has one.
#
# Nothing in here draws. The screens live in the text installer; this is the
# part that can be tested without a terminal.

#: Where to look, in order. The environment first so a test can point at a
#: fixture, the image's own path second, and the source tree last so the text
#: installer runs from a checkout with nothing installed.
aurade_bible_dir() {
  local candidate
  for candidate in \
    "${AURADE_BIBLE_DIR:-}" \
    /usr/local/share/aurade/bible \
    "${BASH_SOURCE[0]%/*}/../bible"; do
    [[ -n $candidate ]] || continue
    [[ -r $candidate/manifest.tsv ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

#: Is there a Bible to offer at all. Everything else is guarded on this, and
#: an image built without one simply never mentions it.
aurade_bible_available() {
  local dir
  dir=$(aurade_bible_dir) || return 1
  [[ -n $dir ]]
}

#: Every book, one per line, as `code<TAB>section<TAB>short<TAB>name<TAB>chapters`.
#
# A row whose file is missing is dropped rather than listed, because a picker
# that offers a book and then opens nothing is worse than one that never
# mentioned it.
aurade_bible_books() {
  local dir
  dir=$(aurade_bible_dir) || return 1
  awk -F'\t' -v dir="$dir" '
    /^#/ || NF != 7 { next }
    {
      path = dir "/" $7
      if ((getline line < path) < 0) next
      close(path)
      printf "%s\t%s\t%s\t%s\t%s\n", $1, $2, $3, $4, $5
    }
  ' "$dir/manifest.tsv"
}

#: How many books there are. Eighty on an image carrying the Apocrypha.
aurade_bible_count() {
  aurade_bible_books | wc -l
}

#: One field of the book at a zero based index. Fields are numbered as in
#: `aurade_bible_books` above, counting from one.
aurade_bible_field() {
  local index=$1 field=$2
  aurade_bible_books | awk -F'\t' -v want="$(( index + 1 ))" -v f="$field" \
    'NR == want { print $f }'
}

#: One chapter of one book, counting chapters from one, as lines to draw.
#
# The book's own title is dropped: the reader shows it above the text already,
# and repeating it at the top of chapter one reads as a mistake rather than as
# a heading.
aurade_bible_chapter() {
  local code=$1 number=$2 dir file
  dir=$(aurade_bible_dir) || return 1
  file=$(awk -F'\t' -v code="$code" '$1 == code { print $7 }' "$dir/manifest.tsv")
  [[ -n $file && -r $dir/$file ]] || return 1
  awk -v want="$number" '
    /^## Chapter / { chapter += 1; next }
    /^# / { next }
    chapter == want { print }
  ' "$dir/$file"
}

#: How many chapters a book has, from the manifest rather than by counting the
#: file, so a truncated file is a visible fault rather than a shorter book.
aurade_bible_chapters() {
  local code=$1 dir
  dir=$(aurade_bible_dir) || return 1
  awk -F'\t' -v code="$code" '$1 == code { print $5 }' "$dir/manifest.tsv"
}
