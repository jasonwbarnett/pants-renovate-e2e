# `BUILD` with no extension at all, which is the first entry in Pants' default
# `build_patterns` and the most canonical build-file name in the ecosystem. The
# bed had every variant of it except this one, and the update script's file list
# was a set of globs none of which matched it -- so the real run claimed this
# file while every check in that script skipped it. The list is derived from the
# manager's own patterns now, so a name cannot be covered by one and missed by
# the other.
python_requirement(
    name="wcwidth",
    requirements=["wcwidth==0.2.14"],
)
