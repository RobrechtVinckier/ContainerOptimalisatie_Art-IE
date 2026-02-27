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

export const COLOR_PALETTE = Object.freeze({
  red: "#c63a3c",
  green: "#2d9f63",
  blue: "#3f66c8",
});

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

export function summarizeStacks(stacks) {
  const colorCount = { red: 0, green: 0, blue: 0 };
  let inTargetSlot = 0;
  let total = 0;

  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      const target = targetColorForSlot(x, z);
      for (const container of stacks[x][z]) {
        colorCount[container.color] += 1;
        if (container.color === target) {
          inTargetSlot += 1;
        }
        total += 1;
      }
    }
  }

  return {
    colorCount,
    total,
    inTargetSlot,
    placementScore: total === 0 ? 1 : inTargetSlot / total,
  };
}
