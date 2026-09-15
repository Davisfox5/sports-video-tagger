// One pending apply per app instance: selection changes, dismiss/reopen,
// project navigation, and a second project's Confirm all respect it, and the
// second project is released once the batch settles.
module.exports = async ({ page, api }) => {
  const passed = [];
  const assert = (ok, label) => { if (!ok) throw new Error(label); passed.push(label); };
  const projects = await api.get("/api/projects");
  const a = projects.find(p => p.name === "Bulk QA Match"), b = projects.find(p => p.name === "Other QA Match");
  for (const p of [a, b]) for (const c of p.clips.slice(0, 2)) await api.put(`/api/projects/${p.id}/clips/${c.id}`, { tag_type: "Goal" });
  let release, ready, requests = 0;
  const held = new Promise(r => { release = r; }), committed = new Promise(r => { ready = r; });
  await page.route("**/clips/bulk_apply", async route => {
    requests++;
    const response = await route.fetch();
    if (requests === 1) { ready(); await held; }
    await route.fulfill({ response });
  });
  const open = async (p, filter = "Goal") => {
    await page.getByText(p.name, { exact: true }).click();
    await page.getByLabel("Filter by tag type").selectOption(filter);
    await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  };
  const back = async () => {
    await page.getByRole("button", { name: "Cancel (Esc)" }).click();
    await page.getByRole("button", { name: "← Projects" }).click();
  };
  const preview = async tag => {
    await page.getByLabel("Tag type", { exact: true }).selectOption(tag);
    await page.getByRole("button", { name: "Preview", exact: true }).click();
    await page.waitForFunction(() => !document.getElementById("btn-bulk-confirm").disabled);
  };
  try {
    await page.reload();
    await open(a); await preview("Pass");
    await page.getByRole("button", { name: "Confirm", exact: true }).click(); await committed;
    await page.getByLabel("Tag type", { exact: true }).selectOption("Shot");
    assert(await page.getByRole("button", { name: "Preview", exact: true }).isDisabled(), "Selection change cannot enable overlapping preview");
    assert(await page.getByRole("button", { name: "Confirm", exact: true }).isDisabled(), "Second confirmation unavailable while first response held");
    await page.getByRole("button", { name: "Cancel (Esc)" }).click();
    await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
    assert(await page.getByRole("button", { name: "Preview", exact: true }).isDisabled(), "Dismiss and reopen preserves pending guard");
    await back(); await open(b); await preview("Pass");
    assert(await page.getByRole("button", { name: "Confirm", exact: true }).isEnabled(), "Other project can prepare a preview");
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    assert(requests === 1, "Global serialization refuses second project apply without losing first marker");
    assert((await page.locator("#bulk-status").innerText()).includes("Applying"), "Blocked second project has visible busy explanation");
    // Release while B's dialog is open: B must be told the wait is over.
    const first = page.waitForResponse(r => r.url().includes(`/projects/${a.id}/clips/bulk_apply`));
    release(); await first;
    await page.locator("#bulk-status").filter({ hasText: "will change" }).waitFor();
    assert(await page.getByRole("button", { name: "Confirm", exact: true }).isEnabled(), "Second project's dialog is released with its own preview after the batch settles");
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await page.locator("#bulk-status").filter({ hasText: "2 clip(s) updated" }).waitFor();
    assert(requests === 2, "Second project can apply after the pending request finishes");
    await back(); await open(a, "Pass");
    assert(await page.locator("#clips-list .clip-card").count() === 2, "Dismissed committed result reconciles when the first project is reopened");
    await preview("Shot");
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await page.locator("#bulk-status").filter({ hasText: "2 clip(s) updated" }).waitFor();
    await page.getByRole("button", { name: "Cancel (Esc)" }).click();
    await page.getByLabel("Filter by tag type").selectOption("Shot");
    const saved = await api.get(`/api/projects/${a.id}`);
    assert(await page.locator("#clips-list .clip-card").count() === 3 && saved.clips.filter(c => c.tag_type === "Shot").length === 3, "Sequential second batch retains all three Shot clips in UI and server");
    return { passed };
  } finally {
    release();
    await page.unroute("**/clips/bulk_apply");
  }
};
