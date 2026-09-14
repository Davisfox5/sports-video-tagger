# Safe bulk tagging

Bulk tagging changes tag type and/or players for the explicit filtered clips. Apply is all-or-nothing.

## Why a lock

`app.py` uses one module-level `threading.RLock`, `_STORE_LOCK`. A small `_locked` decorator holds it for the
entire load-modify-save handler of every route that mutates the project store. Bulk preview and apply
use the same lock. Reads stay unlocked. A clip mutation lands fully before apply and conflicts if it
changed any snapshotted field, or lands fully afterward.

This intentionally serializes writes. Video edit and upload handlers can hold the lock during ffmpeg
or large file work, so these off-match operations can block live tagging for minutes. `_save_projects`
writes to a same-directory temp file and `os.replace`s it, so unlocked reads always see a complete
previous or new file (single-process, POSIX rename semantics).

## Preview store

`_BULK_PREVIEWS` is an in-memory dictionary keyed by a `uuid4().hex` `preview_id`. Each entry is
`{project_id, changes, clips, created}`. `clips` holds a full canonical copy of each affected clip.
Preview mutates this store, not the project store.

The TTL is 10 minutes. Expiry is checked and expired entries are pruned at the start of every
preview/apply; no timer removes idle entries. Abandoned previews remain until lazy pruning.
`expires_in` is the constant 600 seconds at creation and is never refreshed.

Apply pops the entry under `_STORE_LOCK` only when the preview belongs to the requested project.
Simultaneous applies have one winner; the other gets `preview_missing`. Restart empties the store,
so the user must preview again. Filter presets, annotations, recordings, clip timing, labels, and
notes are never changed by apply. Preview timing and labels identify rows, and apply treats any
change to persisted clip content since preview as a `stale` conflict. Response `before`/`after`
values show only the fields the batch can change.

## Contract

### Preview

`POST /api/projects/<pid>/clips/bulk_preview`

```json
{"clip_ids":["c1","c2"],"changes":{"tag_type":"Pass","players":["u1"]}}
```

`clip_ids` is the exact filtered set; the server never re-derives it. There is no separate cap; size
is bounded by one project's clips. A non-empty `players` list replaces the full player set, `[]`
clears it, and omission leaves it unchanged. Player equality is set-based; order is immaterial. At
least one of `tag_type` or `players` is required.

A missing project returns `404 {"error":"Project not found"}`. The missing `code` is deliberate;
clients branch on status for 404.

Invalid input returns `400 {"error":"...","code":"<code>"}`. ID-specific errors also include
`"ids":[...]`, for example `{"error":"Duplicate clip IDs","code":"duplicate_clip_ids","ids":["c1"]}`.
The first failing 400 check wins, in this order:

1. `bad_request`: malformed JSON, a non-object body, a missing `clip_ids`, unsupported keys, or wrong
   field/element types.
2. `no_changes`: neither supported change key is present.
3. `empty_clip_ids`.
4. `duplicate_clip_ids`, listing each duplicate once.
5. `invalid_tag_type`: no entry in `project["tag_types"]` has that `name`.
6. `duplicate_players`, listing each duplicate once.
7. `unknown_players`, listing IDs absent from the project.
8. `unknown_clip_ids`, listing unknown or foreign-project IDs without revealing which case or project.

Success is 200; clips are sorted by `start`:

```json
{"preview_id":"uuid4-hex-or-null","project_id":"p1","changes":{"tag_type":"Pass","players":["u1"]},
 "count":1,"expires_in":600,"clips":[{"id":"c1","start":12.5,"end":18.0,"label":"Counterattack",
 "before":{"tag_type":"Shot","players":[]},"after":{"tag_type":"Pass","players":["u1"]}}]}
```

Set-based player equality determines whether `before` equals `after`. Equal clips are excluded. If
none changes, no preview is stored: `preview_id` is null, `count` is 0, and `clips` is empty.

### Apply

`POST /api/projects/<pid>/clips/bulk_apply` body: `{"preview_id":"uuid4-hex"}`.

Malformed JSON, a non-object body, or a missing, null, empty, or non-string `preview_id` returns
`400 {"error":"...","code":"bad_request"}` without consuming a preview. Otherwise, under
`_STORE_LOCK`, apply prunes expired entries, peeks at the preview, and pops it only when it belongs
to this project:

- Missing, expired, or consumed: 409 `{"error":"Preview expired or already applied — refresh and preview again","code":"preview_missing"}`.
- Different preview `project_id`: 409 `{"error":"...","code":"preview_project_mismatch"}`; `preview_project_mismatch` leaves the preview intact.
- Deleted project: 404 `{"error":"Project not found"}`; no `code` by design.
- Tag type or players no longer valid: 409 `{"error":"...","code":"changes_invalid"}`.

Every preview clip must still exist with identical persisted content (tag_type, set-equal players, start, end, label, notes, annotations, recordings). Otherwise, apply returns 409 and writes nothing:

```json
{"error":"Clips changed after preview; refresh and preview again","code":"stale","conflicts":[
 {"id":"c1","reason":"modified","current":{"tag_type":"Goal","players":[],"start":12.5,
  "end":18.0,"label":"Counterattack","notes":""}},
 {"id":"c2","reason":"deleted","current":null}]}
```

Success makes one `_save_projects()` call and returns `200 {"updated":2,"clip_ids":["c1","c2"]}`.

## Frontend rules

**B** outside an input (and not while another modal is open) opens bulk edit for the filtered
list; existing bindings are I, O, P, and Space. Escape closes. The tagging screen is `inert`
while `#bulk-modal` is active. Any filter/preset/project change, clip-list reload, or bulk
select change discards the client preview without a server delete.

The player select is labelled **Set players to**. Empty (`Keep players`) omits `players`;
`__clear__` (**Clear players**) sends `[]`; a player ID replaces the full list with `[id]`
(not append). **Refresh** re-fetches `/api/projects/<id>` and restores still-valid tag-type
and player choices. Show loading, empty (0 affected), validation, conflict (IDs plus
**Refresh**), and success (count), with accessible labels and a visible **B** binding.

## Apply serialization

`bulkApplyPending` is a single global marker. Confirm (`applyBulkEdit()`) sets it to
`{projectId}` and the request `finally` clears it only when that project's apply
settles. `bulkApplyBusy()` is project-scoped: true only when the marker matches
`currentProject`. The busy UI — status `BULK_APPLY_STATUS` (`Applying… wait for the
current batch`), Preview disabled, Confirm refused — therefore applies in the same
project, including after dismiss/reopen (`closeBulkModal()` then `openBulkModal()`).

Another project may Preview (`previewBulkEdit()` sends POST `bulk_preview`). Its
Confirm is refused until the pending apply settles: `applyBulkEdit()` sees the global
marker, sends no `bulk_apply`, shows `BULK_APPLY_STATUS`, and does not replace the
marker.

Tag type and player (`$bulkTagType.value`, `$bulkPlayer.value`) are captured at
Confirm before `fetch`, so later selector changes do not alter the committed batch.
A settled apply mutates clips and calls `renderClips()` only if that project is still
current; the success status is written after `renderClips()` because rendering
invalidates preview state and would clear it.

## Keyboard and focus

While `#bulk-modal` is `active`, Tab and Shift+Tab (without Ctrl/Meta/Alt) cycle only
enabled, non-hidden `select`/`button` controls in DOM order
(`bulkFocusableControls()`), wrap at both ends, and `preventDefault`. All other
shortcuts (I/O/P/Space/B) are suppressed: the modal `keydown` branch returns without
reaching those bindings. Escape closes the dialog (drops `active`,
`$taggingScreen.inert` is false) and restores focus to `#btn-bulk-edit`.

When Preview, Confirm, or Refresh disable or hide their button, focus is moved
immediately to the next enabled modal control (`keepBulkFocusInside()`) rather than
falling to `body`. Native Enter activation and layout are covered only by
real-browser acceptance.

## Deployment boundary

Only one Flask process serving concurrent request threads is supported. The lock and preview store
are per-process. Multiple workers, including Gunicorn `-w >1`, share neither, so neither lost-update
prevention nor single-apply consumption holds. This is not file locking or multi-process correctness.

## Usage

Filter clips (tag type, player, search, or a saved preset). Press **B** or click **Bulk
edit** (`#btn-bulk-edit`; visible hint `B bulk edit`). The dialog `#bulk-modal` opens
(`role="dialog"` `aria-modal="true"` `aria-labelledby="bulk-modal-title"`), heading
`Bulk edit N filtered clips`, focus on `#bulk-tag-type`.

Choose `#bulk-tag-type`: `Keep tag type` (empty, omit the field) or a project tag type.
Choose `#bulk-player`, labelled **Set players to**: `Keep players` (omit), `Clear players`
(`__clear__`, send `[]`), or a named player (replace the full list with that one ID; not
append). **Preview** posts `{clip_ids, changes}` for the current filter. Confirm starts
disabled and enables only when a non-null preview is stored. The Clip / Before / After
table shows `start–end label` and `tag_type · player names` (`no player` when empty).
Press Enter on the focused **Confirm** button (native) or click it. Success writes
`N clip(s) updated` and resets both selects to keep only if the preview generation
is unchanged. If choices changed or the modal was reopened while applying, the
committed result still appears, current choices are preserved, and the status asks
for a new preview. **Cancel (Esc)** closes.

`#bulk-status` (`role="status"` `aria-live="polite"`):

- empty: `No clips match the current filter`
- validation: `Choose a new tag type or player`
- loading: `Previewing…`, `Applying…`
- no-op: `All selected clips already have these values`
- ready: `N clip(s) will change`
- success: `N clip(s) updated`
- stale: API `error` (normally `Clips changed after preview; refresh and preview again`)
  plus up to five per-clip lines `label: modified (now tag_type · players)` or
  `id: deleted`, then `+N more conflict(s)`; **Refresh** is shown
- other 4xx/network: `error` or `Request failed`; **Refresh** is shown
- refresh: `Refreshing…` then `Refreshed — preview again` (failure: `Refresh failed`)

Changing a filter, preset, selection, project, or reloading the clip list discards the
client preview without a server delete. The tagging screen is `inert` while the modal is
open (I/O/P/Space suppressed; Escape closes).

## Validation

Measured in this slice:

```
$ /tmp/gametape-trial-env/bin/python -m pytest -q
100 passed in 1.96s

$ node --check static/js/app.js
```

`node --check` exited 0 with empty stdout.

`tests/test_bulk_edit.py` groups: persistence of tag/player changes with timing, labels,
notes, annotations, and recordings preserved; explicit player clear; eight 400 codes
(`duplicate_clip_ids`, `unknown_clip_ids`, `invalid_tag_type`, `unknown_players`,
`duplicate_players`, `no_changes`, `empty_clip_ids`, `bad_request`); isolation (untouched
clip and second project); no-op preview; non-consuming `preview_project_mismatch`;
stale-after-edit; deleted-after-preview; `changes_invalid` consumption without
`_save_projects`; simultaneous confirmation (exactly one 200 `{updated: N}`, one 409
`preview_missing`); concurrent unrelated individual edit (neither update lost);
CSV/JSON exports under existing filter semantics and unchanged filter presets.

The wrapped-`_load_projects` barrier parks both threads immediately after each load.
With `@_locked` the second request never reaches that load until the first save
finishes, so the barrier times out and each write sees the other's committed state.
Without the lock both load the same snapshot, wait, then overwrite — a lost update
the assertion would catch. The pattern therefore detects missing serialization rather
than merely issuing sequential requests.

Client interleavings run in a Node-builtins-only VM harness (`tests/ui/fake_dom.js`
plus `tests/ui/load_app.js`): real `templates/index.html` and `static/js/app.js`,
unrelated annotation/recording/video globals stubbed, fetch routes as controlled
promises, no sleeps. `APP_JS_PATH` selects an alternate script.
`tests/ui/load_app.test.js` writes a temporary copy and needs a writable
`os.tmpdir()`.

```
$ node --test tests/ui/*.test.js
ℹ tests 8
ℹ pass 8
ℹ fail 0
```

```
$ node tests/ui/mutation_check.js
```

The mutation script copies `static/js/app.js` to disposable temp files, undoes named
fixes by exact replacement, and runs `tests/ui/bulk_serialization.test.js` and
`tests/ui/bulk_keyboard.test.js` with `APP_JS_PATH` set to each copy (not
`load_app.test.js`). Production `static/js/app.js` is SHA-256 hashed before and after
and remained `a5613bc53459065dbac499f922cab6a0f44d056936c3673e57fc647dfa60707b`.
Final caller-verified results (the mutation subprocess uses uncolored TAP):

```
baseline:                7 passed, 0 failed
late-success-discarded:   5 passed, 2 failed, killed
guard-dropped:            4 passed, 3 failed, killed
capture-after-await:     5 passed, 2 failed, killed
tab-not-prevented:       4 passed, 3 failed, killed
```

The caller strengthened the serialization tests to dispatch real `change` events,
check the committed clip state after dismissal/reopen, and assert the second
request count before awaiting it. Before that correction, restoring the original
generation-based lost-success bug passed all three serialization tests; now it
fails both relevant cases. All four mutants complete with explicit failures and
no cancelled tests. Production code is unchanged by these test corrections.

Limitations: single-process only (see Deployment boundary). `_BULK_PREVIEWS` has no
size cap; idle entries live until 600s lazy prune. `export_video`, `trim_video`,
`split_video`, and `cut_video` hold `_STORE_LOCK` across ffmpeg, stalling every store
mutation including bulk apply. Eight real-browser scenarios were accepted by the
caller, including native Enter activation and layout. The Node harness covers the
deterministic interleavings.
