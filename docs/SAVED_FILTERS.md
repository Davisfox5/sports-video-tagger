# Saved coaching review filters

Choose a tag type, player, and optional search text beside the clip list. Enter
a name and click **Save** (or press Enter in the name field). Select a saved
filter to restore it. To rename it, select it, enter the new name, and click
**Rename**. **Delete** removes the selected preset while leaving clips intact.
Press **P** outside an input to focus the saved-filter selector.

Presets belong to one project and persist in its existing JSON record. Names
are required, limited to 60 characters, and unique within a project without
regard to case. Older projects need no migration. Missing tag/player references
remain selected and are labeled as missing, so a saved restriction never
silently becomes “all.” CSV, JSON, and video export use the restored filters.

## Validation

Run `python -m pytest -q` and `node --check static/js/app.js`.
The 2026-09-13 trial passed 79 tests (69 before this feature). The existing test
fixture now also isolates recording storage under pytest's temporary folder,
so running tests does not create media in the project's data directory.

Chromium acceptance with five synthetic clips verified:

- Saving, browser reload, reopening the project, and restoring the same two clips.
- Downloaded CSV and JSON containing exactly the displayed clip IDs.
- Rename/delete persistence, validation feedback, and keyboard shortcuts.
- Empty and failed-load states and explicit missing tag/player labels.
- Project switching, including delayed preset-list and save responses.
- No JavaScript exceptions during the final acceptance sequence.

The main implementation and ten added backend tests came from Quadratus's
live subscription run. Codex's independent browser review reproduced a delayed
response crossing project views; the follow-up guard discards responses from
an older view, including when reopening the same project.

Quadratus's automated run did not complete: its worker expanded a two-line
fixture task into the remaining feature, hit the invocation timeout, and began
replaying work. The replay was stopped; source was retained and the final
feature was independently tested. This is a verified feature with a supervised
handoff, not evidence of a successful unattended Quadratus run.
