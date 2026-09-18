const API = "https://api.github.com";
const WORKFLOW = "build-iso.yml";
const POLL_MS = 15000;

function headers(token) {
  return {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function api(path, token, init = {}) {
  const response = await fetch(API + path, { ...init, headers: headers(token) });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).message || detail;
    } catch (error) { /* keep statusText */ }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.status === 204 ? null : response.json();
}

/** Start a build and resolve with the run once GitHub has created it. */
export async function dispatchBuild({ repo, token, ref = "main", spec }) {
  const since = Date.now() - 60000;
  await api(`/repos/${repo}/actions/workflows/${WORKFLOW}/dispatches`, token, {
    method: "POST",
    body: JSON.stringify({ ref, inputs: { spec } }),
  });

  for (let attempt = 0; attempt < 12; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const { workflow_runs: runs = [] } = await api(
      `/repos/${repo}/actions/workflows/${WORKFLOW}/runs?event=workflow_dispatch&per_page=5`,
      token,
    );
    const run = runs.find((candidate) => Date.parse(candidate.created_at) >= since);
    if (run) return run;
  }
  throw new Error("dispatched, but the run did not appear — check the Actions tab");
}

/**
 * Poll a run to completion. `onUpdate(run)` fires on every poll.
 * Resolves with { run, artifacts }.
 */
export async function watchRun({ repo, token, runId, onUpdate }) {
  for (;;) {
    const run = await api(`/repos/${repo}/actions/runs/${runId}`, token);
    onUpdate?.(run);
    if (run.status === "completed") {
      const { artifacts = [] } = await api(
        `/repos/${repo}/actions/runs/${runId}/artifacts`,
        token,
      );
      return { run, artifacts };
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

/** Artifact downloads need an authenticated request, so fetch and hand back a blob URL. */
export async function downloadArtifact({ repo, token, artifactId }) {
  const response = await fetch(
    `${API}/repos/${repo}/actions/artifacts/${artifactId}/zip`,
    { headers: headers(token) },
  );
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return URL.createObjectURL(await response.blob());
}
