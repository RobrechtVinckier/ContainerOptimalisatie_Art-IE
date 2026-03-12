const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const fallbackText = await response.text().catch(() => "");
    throw new Error(fallbackText || `Request failed (${response.status})`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function requestRandomConfiguration(options = {}) {
  const normalized = typeof options === "number" ? { seed: options } : options;
  const payload = {
    containerCount: Number.isFinite(normalized.containerCount) ? Number(normalized.containerCount) : 130,
  };
  if (Number.isFinite(normalized.groups)) {
    payload.groups = Number(normalized.groups);
  }
  if (Number.isFinite(normalized.minContainersPerGroup)) {
    payload.minContainersPerGroup = Number(normalized.minContainersPerGroup);
  }
  if (Number.isFinite(normalized.maxContainersPerGroup)) {
    payload.maxContainersPerGroup = Number(normalized.maxContainersPerGroup);
  }
  if (Number.isFinite(normalized.containersPerGroup)) {
    payload.containersPerGroup = Number(normalized.containersPerGroup);
  }
  if (normalized.seed !== null && normalized.seed !== undefined) {
    payload.seed = Number(normalized.seed);
  }

  return request("/api/simulations/random", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function requestSolvePlan(stacks, settings = null) {
  return request("/api/simulations/solve", {
    method: "POST",
    body: JSON.stringify({ stacks, settings }),
  });
}

export async function getAlgorithmSettings() {
  return request("/api/algorithm/settings");
}

export async function updateAlgorithmSettings(settingsPatch) {
  return request("/api/algorithm/settings", {
    method: "PATCH",
    body: JSON.stringify(settingsPatch),
  });
}

export { API_BASE_URL };
