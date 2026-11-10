# Contributing

This is a personal utility, maintained primarily for the author's own use.
Issues and pull requests are welcome; a response, review, fix or merge is not guaranteed.
The maintainer decides which changes fit the project and may close proposals without implementing them.

Keep changes focused on reliable individual monitor power control. Discuss substantial features before writing them.
Preserve the English UI, main-display protection and honest distinction between requested and observed power states.

For a bug, include application and Windows versions, monitor model,
GPU/driver, cable/dock type, and steps to reproduce. Settings offers Copy diagnostics.
Review logs before sharing: they may include display identifiers. Do not include unrelated personal data.

For code changes, install requirements, run `python -m unittest -v` on Windows,
and include regression tests for behavioral fixes. Tests must never power real monitors off.
Describe manual hardware checks separately; do not claim universal DDC/CI compatibility.

By contributing, you agree to license your contribution under this project's MIT license.
