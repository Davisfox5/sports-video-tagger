// The bulk selection changes while the confirmation response is delayed after
// the server committed. The committed result must still land and be displayed.
module.exports = async ({ page, api }) => {
  const a = (await api.get("/api/projects")).find(p => p.name === "Bulk QA Match");
  for (const c of a.clips.slice(0, 2)) await api.put(`/api/projects/${a.id}/clips/${c.id}`, { tag_type: "Goal" });
  await page.reload();
  await page.getByText("Bulk QA Match", { exact: true }).click();
  await page.getByLabel("Filter by tag type").selectOption("Goal");
  await page.getByRole("button", { name: "Bulk edit", exact: true }).click();
  await page.getByLabel("Tag type", { exact: true }).selectOption("Pass");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await page.waitForFunction(() => !document.getElementById("btn-bulk-confirm").disabled);
  let release, serverDone;
  const delayed = new Promise(resolve => { release = resolve; });
  const committed = new Promise(resolve => { serverDone = resolve; });
  await page.route("**/clips/bulk_apply", async route => {
    const response = await route.fetch();
    serverDone();
    await delayed;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await committed;
  await page.getByLabel("Tag type", { exact: true }).selectOption("Shot");
  const response = page.waitForResponse("**/clips/bulk_apply");
  release();
  await response;
  await page.unroute("**/clips/bulk_apply");
  await page.locator("#bulk-status").filter({ hasText: "updated" }).waitFor();
  const project = (await api.get("/api/projects")).find(p => p.name === "Bulk QA Match");
  const result = {
    scenario: "Change bulk selection while confirmation response is delayed after server commit",
    serverGoalClips: project.clips.filter(c => c.tag_type === "Goal").length,
    visibleGoalClips: await page.locator("#clips-list .clip-card").count(),
    filter: await page.getByLabel("Filter by tag type").inputValue(),
    status: await page.locator("#bulk-status").innerText(),
    selection: await page.getByLabel("Tag type", { exact: true }).inputValue(),
  };
  if (result.serverGoalClips !== result.visibleGoalClips || !result.status.includes("updated") || result.selection !== "Shot") throw new Error(JSON.stringify(result));
  return result;
};
