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

export async function requestRandomConfiguration(seed = Date.now()) {
  return request("/api/simulations/random", {
    method: "POST",
    body: JSON.stringify({ seed }),
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
