// Core workflow: preview, confirm, persistence, isolation, exports, reload,
// stale conflict from a second client, refresh. 22 checks.
module.exports = async ({ page, base, api, screenshot }) => {
  const results = [];
  const assert = (condition, name) => { if (!condition) throw new Error(name); results.push(name); };
  await page.getByText("Bulk QA Match", { exact: true }).click();
  const projects = await api.get("/api/projects");
  const before = projects.find(p => p.name === "Bulk QA Match");
  const other = projects.find(p => p.name === "Other QA Match");
  const path = `/api/projects/${before.id}`;
  const selected = before.clips.filter(c => c.tag_type === "Pass");
  assert(selected.length === 2, "Two synthetic Pass clips available");
  await page.getByLabel("Filter by tag type").selectOption("Pass");
  await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  await page.getByLabel("Tag type", { exact: true }).selectOption("Goal");
  await page.getByLabel("Set players to", { exact: true }).selectOption("__clear__");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await page.waitForFunction(() => !document.getElementById("btn-bulk-confirm").disabled);
  assert(await page.locator("#bulk-preview-body tr").count() === 2, "Preview contains exactly two rows");
  assert((await page.locator("#bulk-preview-body").innerText()).includes("Goal · no player"), "Preview shows explicit player clearing");
  await screenshot("preview");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.locator("#bulk-status").filter({ hasText: "2 clip(s) updated" }).waitFor();
  const after = await api.get(path);
  assert(JSON.stringify(after.filter_presets) === JSON.stringify(before.filter_presets), "Saved filter presets preserved");
  for (const old of selected) {
    const current = after.clips.find(c => c.id === old.id);
    assert(current.tag_type === "Goal" && current.players.length === 0, `Persisted tag and clear for ${old.label}`);
    assert(JSON.stringify(current) === JSON.stringify({ ...old, tag_type: "Goal", players: [] }), `Other content preserved for ${old.label}`);
  }
  assert(JSON.stringify(await api.get(`/api/projects/${other.id}`)) === JSON.stringify(other), "Other project unchanged");
  const untouched = c => !selected.some(s => s.id === c.id);
  assert(JSON.stringify(after.clips.find(untouched)) === JSON.stringify(before.clips.find(untouched)), "Unselected clip unchanged");
  assert(await page.locator("#clips-list .clip-card").count() === 0, "Successful edit updates current filtered list");
  await screenshot("success");
  for (const [tag, count] of [["Goal", 2], ["Pass", 0], ["Shot", 1]]) {
    const exported = await api.get(`${path}/export/json?tag_type=${tag}`);
    const csv = await (await page.request.get(`${base}${path}/export/csv?tag_type=${tag}`)).text();
    assert(exported.clip_count === count && csv.trim().split("\n").length === count + 1, `JSON and CSV ${tag} exports reflect batch`);
  }
  await page.reload();
  await page.getByText("Bulk QA Match", { exact: true }).click();
  await page.getByLabel("Filter by tag type").selectOption("Goal");
  assert(await page.locator("#clips-list .clip-card").count() === 2, "Edited clips survive page reload");
  await page.locator("#clip-tag-type").selectOption("Shot");
  await page.locator("#player-checkboxes .player-chip").first().click();
  await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  await page.getByLabel("Tag type", { exact: true }).selectOption("Pass");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await page.waitForFunction(() => !document.getElementById("btn-bulk-confirm").disabled);
  const second = await page.context().newPage();
  await second.goto(base);
  const response = await second.request.put(`${base}${path}/clips/${selected[0].id}`, { data: { notes: `Second browser correction ${Date.now()}` } });
  assert(response.status() === 200, "Second browser edits affected clip after preview");
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.getByRole("button", { name: "Refresh", exact: true }).waitFor();
  const conflicted = await api.get(path);
  assert(selected.every(s => conflicted.clips.find(c => c.id === s.id).tag_type === "Goal"), "Stale confirmation rejects entire batch");
  assert((await page.locator("#bulk-status").innerText()).includes("changed"), "Useful conflict message rendered");
  await screenshot("conflict");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.locator("#bulk-status").filter({ hasText: "Refreshed" }).waitFor();
  assert(await page.getByRole("button", { name: "Confirm", exact: true }).isDisabled(), "Refresh requires a new preview");
  assert(await page.getByLabel("Tag type", { exact: true }).inputValue() === "Pass", "Refresh preserves chosen bulk change");
  assert(await page.locator("#clip-tag-type").inputValue() === "Shot", "Refresh preserves unfinished clip tag");
  assert(await page.locator("#player-checkboxes input").first().isChecked(), "Refresh preserves unfinished clip player");
  await second.close();
  return { passed: results };
};
