# Safe bulk tagging

Bulk tagging changes tag type and/or players for the explicit filtered clips. Apply is all-or-nothing.

## Why a lock

`app.py` has no `threading` import. Every project mutation does `_load_projects()` → mutate →
`_save_projects()` without synchronization. Clip update/delete, annotations, players, presets, tag
types, and video trim/split/cut can therefore lose concurrent writes.

Add one module-level `threading.RLock`, `_STORE_LOCK`. A small `_locked` decorator holds it for the
entire load-modify-save handler of every route that mutates the project store. Bulk preview and apply
use the same lock. Reads stay unlocked. A clip `PUT`/`DELETE` lands fully before apply, and conflicts
if it changed `tag_type` or `players`, or lands fully afterward.

This intentionally serializes writes. Video edit and upload handlers can hold the lock during ffmpeg
or large file work, so these off-match operations can block live tagging for minutes. Unlocked reads
retain the existing risk of observing `_save_projects()` while it truncates and rewrites the JSON;
atomic replacement is outside this slice.

## Preview store

`_BULK_PREVIEWS` is an in-memory dictionary keyed by a `uuid4().hex` `preview_id`. Each entry is
`{project_id, changes, clips: [{id, tag_type, players}], created}`. `clips` is the explicit affected
set and its original relevant state. Preview mutates this store, not the project store.

The TTL is 10 minutes. Expiry is checked and expired entries are pruned at the start of every
preview/apply; no timer removes idle entries. Abandoned previews remain until lazy pruning.
`expires_in` is the constant 600 seconds at creation and is never refreshed.

Apply pops the entry under `_STORE_LOCK`. Simultaneous applies have one winner; the other gets
`preview_missing`. Restart empties the store, so the user must preview again. Filter presets,
annotations, recordings, clip timing, labels, and notes are never changed. Preview timing and labels
identify rows only; concurrent changes to them do not cause a stale conflict.

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

1. `bad_request`: malformed JSON, a non-object body, unsupported keys, or wrong field/element types.
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
`_STORE_LOCK`, apply prunes expired entries, pops the preview, and returns as needed:

- Missing, expired, or consumed: 409 `{"error":"Preview expired or already applied — refresh and preview again","code":"preview_missing"}`.
- Different preview `project_id`: 409 `{"error":"...","code":"preview_project_mismatch"}`.
- Deleted project: 404 `{"error":"Project not found"}`; no `code` by design.
- Tag type or players no longer valid: 409 `{"error":"...","code":"changes_invalid"}`.

Every preview clip must still exist with its original `tag_type` and set-equal `players`. Otherwise,
apply returns 409 and writes nothing:

```json
{"error":"Clips changed after preview; refresh and preview again","code":"stale","conflicts":[
 {"id":"c1","reason":"modified","current":{"tag_type":"Goal","players":[]}},
 {"id":"c2","reason":"deleted","current":null}]}
```

Success makes one `_save_projects()` call and returns `200 {"updated":2,"clip_ids":["c1","c2"]}`.

## Frontend rules

**B** outside an input opens bulk edit for the filtered list; existing bindings are I, O, P, and
Space. Escape closes. Any filter/preset/project change or clip-list reload discards the client
preview without a server delete. Show loading, empty (0 affected), validation, conflict (IDs plus
**Refresh**), and success (count), with accessible labels and a visible **B** binding.

## Deployment boundary

Only one Flask process serving concurrent request threads is supported. The lock and preview store
are per-process. Multiple workers, including Gunicorn `-w >1`, share neither, so neither lost-update
prevention nor single-apply consumption holds. This is not file locking or multi-process correctness.

## Usage

To be completed in a later slice.

## Validation

To be completed in a later slice.
