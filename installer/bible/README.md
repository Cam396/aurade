# The King James Version, with the Apocrypha

Eighty books, 1,362 chapters, 36,822 verses. One markdown file per book, named
by its three letter code, indexed by `manifest.tsv`.

## Where it came from

`eng-kjv_usfm.zip` in this directory, downloaded from
<https://ebible.org/Scriptures/eng-kjv_usfm.zip> on 17 August 2026, SHA256
`0079b6db44fff5ffe124015f81fc67a023388d22aba50c012fcf48670e683a25`. It is
eBible.org's `eng-kjv`, the 1769 standardised text, carrying the Apocrypha.
`tools/make-bible.py` pins that checksum and refuses to run against anything
else, because a different Bible that happens to parse cleanly is the failure
worth catching.

**Watch out for `engKJV`**, which is a different edition on the same site with
a near identical name and the protocanon only. The one with the Apocrypha is
the hyphenated `eng-kjv`. Three of the four sources that were checked first
turned out to be sixty six books, and this is the distinction that separates
them.

The zip is committed rather than fetched during the build. A build that
reaches for the network stops working the day the network does, and having the
source in the tree is what lets `test-bible.sh` re-derive all eighty books and
compare rather than merely inspecting what is already there.

## Licence

Public domain. The King James Version was published in 1611 and its text has
been out of copyright everywhere for centuries; eBible.org distributes this
edition as public domain, by way of the Crosswire Bible Society.

The one wrinkle worth knowing rather than worrying about: in the **United
Kingdom** the KJV is covered by the Queen's Printer's Patent, a perpetual
Crown prerogative administered by Cambridge University Press, which restricts
*printing* it there. It is not a copyright, it has no bearing on distributing
a text file, and it is a different situation in every respect from the reason
this project will not ship the NIV. That one is live commercial copyright held
by Biblica and Zondervan, and bundling it in a distributed image would be
infringement landing on whoever ships the ISO.

## What the conversion drops

**Footnotes.** Six thousand nine hundred and fifty nine translator notes, each
an aside about a Hebrew idiom or a variant reading. Inline they would break
every other sentence in half, and this is a thing to read while an operating
system installs rather than an apparatus to study with.

**The red letter.** USFM marks the words of Jesus. Markdown has no colour, so
the marking is dropped rather than approximated with something louder than the
printed convention it stands for.

**Strong's numbers.** Three hundred and thirteen thousand of them, wrapped
around very nearly every word. They are why the source archive is larger than
the text it contains.

## What the conversion keeps

**The italics**, as markdown emphasis. The KJV has always printed the words
its translators supplied rather than found in the source, and that is the most
useful piece of typography in the book: it marks the difference between what
the text says and what the translation needed in order to read as English.
Emphasis is exactly what that means, so that is what it becomes.

**The paragraphing, the poetry and the Psalm superscriptions.** Hebrew poetry
set as prose is not the same poem.

## The shape of a file

    # The First Book of Moses, called Genesis

    ## Chapter 1

    1 In the beginning God created the heaven and the earth.

One verse per line, numbered, so that both front ends can render it by walking
lines and neither needs a markdown engine. The text installer draws in a
terminal and the graphical one draws in a label, and neither has one. Poetry
keeps its own line breaks inside a verse; a blank line is a paragraph break
where the source marked one.

## Regenerating

    installer/tools/make-bible.py            # rewrite the eighty files
    installer/tools/make-bible.py --check    # fail if the tree has drifted

`test-bible.sh` runs the check, so what is committed here is always what the
converter produces from the archive committed beside it.
