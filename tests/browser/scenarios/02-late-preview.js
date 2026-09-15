// A preview response that arrives after the dialog was dismissed and the
// filter changed must not restore the stale rows or enable Confirm.
module.exports = async ({ page, api }) => {
  const a = (await api.get("/api/projects")).find(p => p.name === "Bulk QA Match");
  for (const c of a.clips.slice(0, 2)) await api.put(`/api/projects/${a.id}/clips/${c.id}`, { tag_type: "Goal" });
  await page.reload();
  await page.getByText("Bulk QA Match", { exact: true }).click();
  await page.getByLabel("Filter by tag type").selectOption("Goal");
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route("**/clips/bulk_preview", async route => { await delayed; await route.continue(); });
  await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  await page.getByLabel("Tag type", { exact: true }).selectOption("Pass");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Previewing" }).waitFor();
  await page.getByRole("button", { name: "Cancel (Esc)" }).click();
  await page.getByLabel("Filter by tag type").selectOption("Shot");
  await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  const response = page.waitForResponse("**/clips/bulk_preview");
  release();
  await response;
  await page.waitForFunction(() => !document.getElementById("btn-bulk-preview").disabled);
  const result = {
    confirmDisabled: await page.getByRole("button", { name: "Confirm", exact: true }).isDisabled(),
    rows: await page.locator("#bulk-preview-body tr").count(),
    heading: await page.getByRole("heading", { name: /Bulk edit/ }).innerText(),
  };
  await page.unroute("**/clips/bulk_preview");
  if (!result.confirmDisabled || result.rows !== 0 || !result.heading.includes("1 filtered")) throw new Error("Late preview restored stale state: " + JSON.stringify(result));
  return result;
};
