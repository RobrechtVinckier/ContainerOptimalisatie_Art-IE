export const YARD_CONFIG = Object.freeze({
  width: 5,
  length: 10,
  height: 4,
  truckLaneWidth: 1,
  containerMeters: Object.freeze({
    length: 12.19,
    width: 2.44,
    height: 2.59,
  }),
  containerCount: 130,
  lengthCostWeight: 10,
});

export const COLOR_ORDER = Object.freeze(["red", "green", "blue"]);

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

const NETWORK_DELAY = Object.freeze({
  generateMin: 280,
  generateMax: 520,
  solveMin: 420,
  solveMax: 760,
});

export function createEmptyStacks() {
  return Array.from({ length: YARD_CONFIG.width }, () =>
    Array.from({ length: YARD_CONFIG.length }, () => []),
  );
}

export function cloneStacks(stacks) {
  return stacks.map((columns) => columns.map((stack) => stack.map((container) => ({ ...container }))));
}

export function targetColorForSlot(x, z) {
  return TARGET_PATTERNS[z % TARGET_PATTERNS.length][x];
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(min, max) {
  return Math.floor(min + Math.random() * (max - min));
}

function hashSeed(seed) {
  const text = String(seed);
  let hashed = 1779033703 ^ text.length;
  for (let i = 0; i < text.length; i += 1) {
    hashed = Math.imul(hashed ^ text.charCodeAt(i), 3432918353);
    hashed = (hashed << 13) | (hashed >>> 19);
  }
  return () => {
    hashed = Math.imul(hashed ^ (hashed >>> 16), 2246822507);
    hashed = Math.imul(hashed ^ (hashed >>> 13), 3266489909);
    hashed ^= hashed >>> 16;
    return hashed >>> 0;
  };
}

function mulberry32(seed) {
  return function generator() {
    let value = (seed += 0x6d2b79f5);
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function weightedDistance(from, to) {
  return Math.abs(from.x - to.x) + YARD_CONFIG.lengthCostWeight * Math.abs(from.z - to.z);
}

function stackPureForTarget(stack, target) {
  return stack.every((container) => container.color === target);
}

function stackNeedsWork(stack, target) {
  return !stackPureForTarget(stack, target);
}

function allCoords() {
  const coords = [];
  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      coords.push({ x, z });
    }
  }
  return coords;
}

function executeMove(stacks, from, to) {
  const source = stacks[from.x][from.z];
  const destination = stacks[to.x][to.z];
  const container = source.pop();

  if (!container) {
    throw new Error(`Illegal move: source stack (${from.x}, ${from.z}) is empty.`);
  }

  if (destination.length >= YARD_CONFIG.height) {
    throw new Error(`Illegal move: destination stack (${to.x}, ${to.z}) is full.`);
  }

  const move = {
    id: container.id,
    color: container.color,
    from: { x: from.x, z: from.z, y: source.length },
    to: { x: to.x, z: to.z, y: destination.length },
  };

  destination.push(container);
  return move;
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

export function isSolved(stacks) {
  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      const target = targetColorForSlot(x, z);
      for (const container of stacks[x][z]) {
        if (container.color !== target) {
          return false;
        }
      }
    }
  }

  return true;
}

export async function requestRandomConfiguration(seed = Date.now()) {
  await wait(randomDelay(NETWORK_DELAY.generateMin, NETWORK_DELAY.generateMax));

  const createSeed = hashSeed(seed);
  const random = mulberry32(createSeed());
  const stacks = createEmptyStacks();
  const heights = Array.from({ length: YARD_CONFIG.width }, () =>
    Array.from({ length: YARD_CONFIG.length }, () => 0),
  );

  let remaining = YARD_CONFIG.containerCount;

  while (remaining > 0) {
    const x = Math.floor(random() * YARD_CONFIG.width);
    const z = Math.floor(random() * YARD_CONFIG.length);

    if (heights[x][z] >= YARD_CONFIG.height) {
      continue;
    }

    heights[x][z] += 1;
    remaining -= 1;
  }

  let idCounter = 1;
  for (let x = 0; x < YARD_CONFIG.width; x += 1) {
    for (let z = 0; z < YARD_CONFIG.length; z += 1) {
      for (let y = 0; y < heights[x][z]; y += 1) {
        const color = COLOR_ORDER[Math.floor(random() * COLOR_ORDER.length)];
        stacks[x][z].push({
          id: `C${String(idCounter).padStart(4, "0")}`,
          color,
        });
        idCounter += 1;
      }
    }
  }

  return {
    seed,
    stacks,
    summary: summarizeStacks(stacks),
  };
}

function findProductiveMove(stacks, coordinates, lastMove) {
  let bestWrongTop = null;
  let bestBlocking = null;

  for (const source of coordinates) {
    const sourceStack = stacks[source.x][source.z];
    if (sourceStack.length === 0) {
      continue;
    }

    const sourceTarget = targetColorForSlot(source.x, source.z);
    const sourcePure = stackPureForTarget(sourceStack, sourceTarget);
    if (sourcePure) {
      continue;
    }

    const topContainer = sourceStack[sourceStack.length - 1];
    const topWrong = topContainer.color !== sourceTarget;

    for (const destination of coordinates) {
      if (destination.x === source.x && destination.z === source.z) {
        continue;
      }

      const destinationStack = stacks[destination.x][destination.z];
      if (destinationStack.length >= YARD_CONFIG.height) {
        continue;
      }

      const destinationTarget = targetColorForSlot(destination.x, destination.z);
      if (destinationTarget !== topContainer.color) {
        continue;
      }

      if (!destinationStack.every((container) => container.color === topContainer.color)) {
        continue;
      }

      if (
        lastMove
        && lastMove.id === topContainer.id
        && lastMove.from.x === destination.x
        && lastMove.from.z === destination.z
        && lastMove.to.x === source.x
        && lastMove.to.z === source.z
      ) {
        continue;
      }

      const score = weightedDistance(source, destination);
      const candidate = { from: source, to: destination, score };

      if (topWrong) {
        if (!bestWrongTop || candidate.score < bestWrongTop.score) {
          bestWrongTop = candidate;
        }
      } else if (!bestBlocking || candidate.score < bestBlocking.score) {
        bestBlocking = candidate;
      }
    }
  }

  return bestWrongTop || bestBlocking;
}

function findBufferMove(stacks, coordinates, lastMove) {
  let best = null;

  for (const source of coordinates) {
    const sourceStack = stacks[source.x][source.z];
    if (sourceStack.length === 0) {
      continue;
    }

    const sourceTarget = targetColorForSlot(source.x, source.z);
    if (!stackNeedsWork(sourceStack, sourceTarget)) {
      continue;
    }

    const topContainer = sourceStack[sourceStack.length - 1];

    for (const destination of coordinates) {
      if (destination.x === source.x && destination.z === source.z) {
        continue;
      }

      const destinationStack = stacks[destination.x][destination.z];
      if (destinationStack.length >= YARD_CONFIG.height) {
        continue;
      }

      if (
        lastMove
        && lastMove.id === topContainer.id
        && lastMove.from.x === destination.x
        && lastMove.from.z === destination.z
        && lastMove.to.x === source.x
        && lastMove.to.z === source.z
      ) {
        continue;
      }

      const destinationTarget = targetColorForSlot(destination.x, destination.z);
      const destinationPureTarget =
        destinationStack.length > 0 && stackPureForTarget(destinationStack, destinationTarget);

      if (destinationPureTarget && topContainer.color !== destinationTarget) {
        continue;
      }

      let score = weightedDistance(source, destination);
      if (topContainer.color !== destinationTarget) {
        score += destinationStack.length === 0 ? 18 : 8;
      }

      const sameColorOnTop =
        destinationStack.length > 0
        && destinationStack[destinationStack.length - 1].color === topContainer.color;
      if (sameColorOnTop) {
        score -= 2;
      }

      const topWrong = topContainer.color !== sourceTarget;
      if (topWrong) {
        score -= 4;
      }

      const candidate = { from: source, to: destination, score };
      if (!best || candidate.score < best.score) {
        best = candidate;
      }
    }
  }

  return best;
}

export async function requestSolvePlan(initialStacks) {
  await wait(randomDelay(NETWORK_DELAY.solveMin, NETWORK_DELAY.solveMax));

  const working = cloneStacks(initialStacks);
  const coordinates = allCoords();
  const moves = [];

  let iterations = 0;
  let lastMove = null;
  const maxIterations = 1800;

  while (iterations < maxIterations && !isSolved(working)) {
    const productive = findProductiveMove(working, coordinates, lastMove);
    const chosen = productive || findBufferMove(working, coordinates, lastMove);

    if (!chosen) {
      break;
    }

    const move = executeMove(working, chosen.from, chosen.to);
    move.weightedCost = weightedDistance(move.from, move.to);
    moves.push(move);
    lastMove = move;
    iterations += 1;
  }

  const totalWeightedCost = moves.reduce((sum, move) => sum + move.weightedCost, 0);
  const summary = summarizeStacks(working);

  return {
    moves,
    solved: isSolved(working),
    totalWeightedCost,
    finalSummary: summary,
    finalStacks: working,
  };
}
