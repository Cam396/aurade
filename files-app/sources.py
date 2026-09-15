"""Every file the page is built from.

build_v3.py generates the markup from the contracts and the page's own
stylesheet and script are in css/ and js/, one file per section. Anything
that reads the builder's source rather than the built page, the static
gates, the accounting tools and the build id, reads all of it through here,
so a caption or a sink cannot hide in a file the reader did not know about.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _dir(sub):
    d = os.path.join(HERE, sub)
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.endswith("." + sub)]


def css():
    return _dir("css")


def js():
    return _dir("js")


def files():
    return [os.path.join(HERE, "build_v3.py")] + css() + js()


def text():
    return "".join(open(f, encoding="utf-8").read() for f in files())
