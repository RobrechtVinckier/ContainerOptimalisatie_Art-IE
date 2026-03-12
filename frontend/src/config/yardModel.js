export const YARD_CONFIG = Object.freeze({
  width: 5,
  length: 10,
  height: 4,
  truckLaneWidth: 2,
  containerMeters: Object.freeze({
    length: 12.19,
    width: 2.44,
    height: 2.59,
  }),
  containerCount: 130,
  lengthCostWeight: 10,
});

const DEFAULT_PLACEMENT_SCORE_WEIGHTS = Object.freeze({
  cluster: 0.1,
  topMismatch: 1.8,
  transitions: 1.6,
  rehandles: 1.4,
  impurity: 0.6,
  buriedForeign: 2.6,
  fragmentation: 0.1,
});

const PREFERRED_TOP_WAVE_DEPTH = 3;

export const COLOR_PALETTE = Object.freeze({
  red: "#c63a3c",
  green: "#2d9f63",
  blue: "#3f66c8",
});

function hashTextToUint32(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function hslToHex(h, s, l) {
  const sat = s / 100;
  const light = l / 100;
  const c = (1 - Math.abs(2 * light - 1)) * sat;
  const hp = h / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let r1 = 0;
  let g1 = 0;
  let b1 = 0;

  if (hp >= 0 && hp < 1) {
    r1 = c;
    g1 = x;
  } else if (hp < 2) {
    r1 = x;
    g1 = c;
  } else if (hp < 3) {
    g1 = c;
    b1 = x;
  } else if (hp < 4) {
    g1 = x;
    b1 = c;
  } else if (hp < 5) {
    r1 = x;
    b1 = c;
  } else {
    r1 = c;
    b1 = x;
  }

  const m = light - c / 2;
  const toHex = (channel) => Math.round((channel + m) * 255).toString(16).padStart(2, "0");
  return `#${toHex(r1)}${toHex(g1)}${toHex(b1)}`;
}

function generatedColorHex(key) {
  const hash = hashTextToUint32(key);
  const hue = hash % 360;
  const saturation = 62 + ((hash >>> 8) % 14);
  const lightness = 46 + ((hash >>> 16) % 10);
  return hslToHex(hue, saturation, lightness);
}

export function resolveColorHex(colorName) {
  if (typeof colorName !== "string") {
    return "#60768b";
  }

  const normalized = colorName.trim();
  if (!normalized) {
    return "#60768b";
  }
  if (Object.prototype.hasOwnProperty.call(COLOR_PALETTE, normalized)) {
    return COLOR_PALETTE[normalized];
  }
  if (/^#[0-9a-fA-F]{6}$/.test(normalized)) {
    return normalized;
  }

  return generatedColorHex(normalized);
}

const TARGET_PATTERNS = [
  ["red", "green", "blue", "red", "green"],
  ["green", "blue", "red", "green", "blue"],
  ["blue", "red", "green", "blue", "red"],
];

export function targetColorForSlot(x, z) {
  return TARGET_PATTERNS[z % TARGET_PATTERNS.length][x];
}

export function cloneStacks(stacks) {
  return stacks.map((columns) => columns.map((stack) => stack.map((container) => ({ ...container }))));
}

function nonNegativeNumber(value, fallback) {
  return Number.isFinite(value) ? Math.max(0, Number(value)) : fallback;
}

function resolvePlacementScoreWeights(weights) {
  const resolved = { ...DEFAULT_PLACEMENT_SCORE_WEIGHTS };
  if (!weights || typeof weights !== "object") {
    return resolved;
  }
  resolved.cluster = nonNegativeNumber(weights.cluster, resolved.cluster);
  resolved.topMismatch = nonNegativeNumber(weights.topMismatch, resolved.topMismatch);
  resolved.transitions = nonNegativeNumber(weights.transitions, resolved.transitions);
  resolved.rehandles = nonNegativeNumber(weights.rehandles, resolved.rehandles);
  resolved.impurity = nonNegativeNumber(weights.impurity, resolved.impurity);
  resolved.buriedForeign = nonNegativeNumber(weights.buriedForeign, resolved.buriedForeign);
  resolved.fragmentation = nonNegativeNumber(weights.fragmentation, resolved.fragmentation);
  return resolved;
}

export function placementScoreWeightsFromAlgorithmSettings(settings) {
  if (!settings || typeof settings !== "object") {
    return null;
  }
  return resolvePlacementScoreWeights({
    cluster: settings.lam ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.cluster,
    topMismatch: settings.stackTopMismatchWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.topMismatch,
    transitions: settings.stackTransitionWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.transitions,
    rehandles: settings.stackRehandleWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.rehandles,
    impurity: settings.stackImpurityWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.impurity,
    buriedForeign: settings.buriedForeignWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.buriedForeign,
    fragmentation: settings.groupFragmentationWeight ?? DEFAULT_PLACEMENT_SCORE_WEIGHTS.fragmentation,
  });
}

export function summarizeStacks(stacks, scoreWeights = null) {
  const resolvedWeights = resolvePlacementScoreWeights(scoreWeights);
  const wCluster = resolvedWeights.cluster;
  const wTopMismatch = resolvedWeights.topMismatch;
  const wTransitions = resolvedWeights.transitions;
  const wRehandles = resolvedWeights.rehandles;
  const wImpurity = resolvedWeights.impurity;
  const wBuriedForeign = resolvedWeights.buriedForeign;
  const wFragmentation = resolvedWeights.fragmentation;

  const colorCount = { red: 0, green: 0, blue: 0 };
  const colorBounds = {};
  const colorStackOccupancy = {};
  let total = 0;
  let topMismatchPenalty = 0;
  let transitionPenalty = 0;
  let rehandlesPenalty = 0;
  let impurityPenalty = 0;
  let buriedForeignPenalty = 0;
  let maxTopMismatch = 0;
  let maxTransitions = 0;
  let maxRehandles = 0;
  let maxImpurity = 0;
  let maxBuriedForeign = 0;

  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      const stack = stacks[x][z];
      const n = stack.length;
      if (n > 0) {
        const countsInStack = {};
        const colorsSeen = new Set();
        for (const container of stack) {
          const colorName = container.color;
          countsInStack[colorName] = (countsInStack[colorName] || 0) + 1;
          colorsSeen.add(colorName);
        }
        const topColor = stack[n - 1].color;
        let topRun = 0;
        for (let idx = n - 1; idx >= 0; idx -= 1) {
          if (stack[idx].color !== topColor) {
            break;
          }
          topRun += 1;
        }
        const usefulTarget = Math.min(n, PREFERRED_TOP_WAVE_DEPTH);
        topMismatchPenalty += Math.max(0, usefulTarget - topRun);
        impurityPenalty += n - Math.max(...Object.values(countsInStack));
        maxTopMismatch += usefulTarget;
        maxTransitions += Math.max(0, n - 1);
        maxImpurity += Math.max(0, n - 1);
        maxRehandles += (n * (n - 1)) / 2;
        maxBuriedForeign += (n * (n - 1) * (n + 1)) / 6;

        for (const colorName of colorsSeen) {
          colorStackOccupancy[colorName] = (colorStackOccupancy[colorName] || 0) + 1;
        }

        for (let lower = 0; lower < n; lower += 1) {
          const lowerColor = stack[lower].color;
          for (let upper = lower + 1; upper < n; upper += 1) {
            if (stack[upper].color !== lowerColor) {
              rehandlesPenalty += 1;
              buriedForeignPenalty += (upper - lower);
            }
          }
        }
        for (let idx = n - 1; idx > 0; idx -= 1) {
          if (stack[idx].color !== stack[idx - 1].color) {
            transitionPenalty += 1;
          }
        }
      }

      for (const container of stack) {
        if (!Object.prototype.hasOwnProperty.call(colorCount, container.color)) {
          colorCount[container.color] = 0;
        }
        colorCount[container.color] += 1;

        if (!Object.prototype.hasOwnProperty.call(colorBounds, container.color)) {
          colorBounds[container.color] = {
            minX: x,
            maxX: x,
            minZ: z,
            maxZ: z,
          };
        } else {
          const bounds = colorBounds[container.color];
          bounds.minX = Math.min(bounds.minX, x);
          bounds.maxX = Math.max(bounds.maxX, x);
          bounds.minZ = Math.min(bounds.minZ, z);
          bounds.maxZ = Math.max(bounds.maxZ, z);
        }
        total += 1;
      }
    }
  }

  let clusterCost = 0;
  let activeGroups = 0;
  for (const [colorName, count] of Object.entries(colorCount)) {
    if (count <= 0) {
      continue;
    }
    const bounds = colorBounds[colorName];
    const spanX = bounds.maxX - bounds.minX;
    const spanZ = bounds.maxZ - bounds.minZ;
    clusterCost += 2 * spanZ + 0.5 * spanX;
    activeGroups += 1;
  }

  let fragmentationPenalty = 0;
  let maxFragmentation = 0;
  const totalStacks = YARD_CONFIG.width * YARD_CONFIG.length;
  for (const [colorName, count] of Object.entries(colorCount)) {
    if (count <= 0) {
      continue;
    }
    const occupied = colorStackOccupancy[colorName] || 0;
    if (occupied > 0) {
      fragmentationPenalty += occupied - 1;
    }
    const maxOcc = Math.min(count, totalStacks);
    if (maxOcc > 0) {
      maxFragmentation += maxOcc - 1;
    }
  }

  const maxSpreadPerGroup = 2 * (YARD_CONFIG.length - 1) + 0.5 * (YARD_CONFIG.width - 1);
  const maxClusterCost = activeGroups * maxSpreadPerGroup;
  const normCluster = maxClusterCost > 0 ? (clusterCost / maxClusterCost) : 0;
  const normTop = maxTopMismatch > 0 ? (topMismatchPenalty / maxTopMismatch) : 0;
  const normTransitions = maxTransitions > 0 ? (transitionPenalty / maxTransitions) : 0;
  const normRehandles = maxRehandles > 0 ? (rehandlesPenalty / maxRehandles) : 0;
  const normImpurity = maxImpurity > 0 ? (impurityPenalty / maxImpurity) : 0;
  const normBuried = maxBuriedForeign > 0 ? (buriedForeignPenalty / maxBuriedForeign) : 0;
  const normFragmentation = maxFragmentation > 0 ? (fragmentationPenalty / maxFragmentation) : 0;

  const weightedNorm = (
    wCluster * normCluster
    + wTopMismatch * normTop
    + wTransitions * normTransitions
    + wRehandles * normRehandles
    + wImpurity * normImpurity
    + wBuriedForeign * normBuried
    + wFragmentation * normFragmentation
  );
  const weightTotal = wCluster + wTopMismatch + wTransitions + wRehandles + wImpurity + wBuriedForeign + wFragmentation;
  const placementScore = weightTotal <= 0
    ? 1
    : Math.max(0, Math.min(1, 1 - (weightedNorm / weightTotal)));
  const inTargetSlot = Math.round(placementScore * total);

  return {
    colorCount,
    total,
    inTargetSlot,
    placementScore,
  };
}
