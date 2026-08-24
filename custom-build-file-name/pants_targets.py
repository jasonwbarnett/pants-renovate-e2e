# `build_patterns` in pants.toml allows this name. Renovate decides what a
# file is from the targets inside it, so updates work here too.
python_requirement(
    name="rich",
    requirements=["rich==15.0.0"],
    resolve="tools",
)
