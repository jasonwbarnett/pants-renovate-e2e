# Adding a dependency

Pants' default `build_patterns` match this file, and Renovate's default
`managerFilePatterns` follow them, so this file is handed to the pants manager.
It is prose, and Pants itself never reads it, so nothing in it is a dependency.

Declare a single requirement like this:

```python
python_requirement(name="flask", requirements=["flask==1.1.2"])
```

For a whole file of them, use a generator:

```python
python_requirements(name="reqs", source="requirements.txt")
```

Neither the pin above nor the file named beside it may be reported.
