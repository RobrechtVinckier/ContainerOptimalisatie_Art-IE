const DAY_TRUCK_PHASES = Object.freeze({
  scheduled: "scheduled",
  enteringRoad: "enteringRoad",
  drivingToParkingBay: "drivingToParkingBay",
  parkingBay: "parkingBay",
  waiting: "waiting",
  loading: "loading",
  loaded: "loaded",
  mergingOut: "mergingOut",
  departing: "departing",
  finished: "finished",
});

const DAY_CRANE_PHASES = Object.freeze({
  idle: "idle",
  executing: "executing",
});

const DEFAULTS = Object.freeze({
  fixedStepSeconds: 0.25,
  maxFixedStepsPerFrame: 600,
  entryProgressDistance: 2.8,
  approachBuffer: 3.1,
  nominalRoadSpeed: 5.8,
  roadAcceleration: 5.6,
  roadBraking: 10.5,
  stopDistance: 5.4,
  brakingDistance: 11.8,
  truckLength: 7.4,
  bayClearance: 8.1,
  entrySpacing: 9.4,
  mergeClearanceAhead: 8.8,
  mergeClearanceBehind: 15.0,
  parkingDuration: 2.5,
  mergeDuration: 2.2,
  mergeAdvanceDistance: 4.1,
});

const PHASES_USING_LANE = new Set([
  DAY_TRUCK_PHASES.enteringRoad,
  DAY_TRUCK_PHASES.drivingToParkingBay,
  DAY_TRUCK_PHASES.mergingOut,
  DAY_TRUCK_PHASES.departing,
]);

const PHASES_OCCUPYING_BAY = new Set([
  DAY_TRUCK_PHASES.parkingBay,
  DAY_TRUCK_PHASES.waiting,
  DAY_TRUCK_PHASES.loading,
  DAY_TRUCK_PHASES.loaded,
  DAY_TRUCK_PHASES.mergingOut,
]);

function clamp01(value) {
  return Math.max(0, Math.min(1, value));
}

function easeInOutCubic(value) {
  const t = clamp01(value);
  if (t < 0.5) {
    return 4 * t * t * t;
  }
  return 1 - ((-2 * t + 2) ** 3) / 2;
}

function lerp(start, end, t) {
  return start + (end - start) * t;
}

function moveTowards(current, target, maxDelta) {
  if (current < target) {
    return Math.min(target, current + maxDelta);
  }
  return Math.max(target, current - maxDelta);
}

function phaseOrderValue(phase) {
  const order = [
    DAY_TRUCK_PHASES.scheduled,
    DAY_TRUCK_PHASES.enteringRoad,
    DAY_TRUCK_PHASES.drivingToParkingBay,
    DAY_TRUCK_PHASES.parkingBay,
    DAY_TRUCK_PHASES.waiting,
    DAY_TRUCK_PHASES.loading,
    DAY_TRUCK_PHASES.loaded,
    DAY_TRUCK_PHASES.mergingOut,
    DAY_TRUCK_PHASES.departing,
    DAY_TRUCK_PHASES.finished,
  ];
  const index = order.indexOf(phase);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function getSlotZ(layout, job) {
  const mapped = Array.isArray(layout.slotZ) ? layout.slotZ[job.slotIndex] : undefined;
  if (Number.isFinite(mapped)) {
    return Number(mapped);
  }
  return Number.isFinite(job.slotZ) ? Number(job.slotZ) : layout.entryZ;
}

function createTruckActor(job, index, layout, road) {
  const slotZ = getSlotZ(layout, job);
  return {
    key: `${job.truckId}:${index}`,
    jobIndex: index,
    job,
    truckId: job.truckId,
    company: job.company,
    companyColor: job.companyColor,
    slotZ,
    holdZ: Math.max(layout.entryZ + 1.4, slotZ - road.approachBuffer),
    x: layout.passingLaneX,
    z: layout.entryZ,
    heading: 0,
    visible: false,
    speed: 0,
    nominalRoadSpeed: road.nominalRoadSpeed,
    phase: DAY_TRUCK_PHASES.scheduled,
    phaseChangedAt: 0,
    parkedAt: null,
    loadedAt: null,
    departureReadyAt: Number.isFinite(job.departTime) ? Number(job.departTime) : 0,
    maneuver: null,
    cargoVisible: false,
    cranePlan: null,
    pickedContainerId: null,
    completionCounted: false,
  };
}

function notifyPhaseChange(runtime, actor, nextPhase, time, hooks) {
  if (actor.phase === nextPhase) {
    return;
  }
  const previousPhase = actor.phase;
  actor.phase = nextPhase;
  actor.phaseChangedAt = time;
  if (hooks?.onTruckPhaseChange) {
    hooks.onTruckPhaseChange(actor, previousPhase, nextPhase, time, runtime);
  }
}

function startManeuver(runtime, actor, nextPhase, time, config, hooks) {
  actor.speed = 0;
  actor.maneuver = {
    startTime: time,
    duration: Math.max(0.05, Number(config.duration) || 0.05),
    startX: actor.x,
    startZ: actor.z,
    startHeading: actor.heading,
    endX: config.endX,
    endZ: config.endZ,
    endHeading: config.endHeading ?? 0,
    completePhase: config.completePhase,
  };
  notifyPhaseChange(runtime, actor, nextPhase, time, hooks);
}

function getLaneActors(runtime) {
  return runtime.truckActors
    .filter((actor) => actor.visible && PHASES_USING_LANE.has(actor.phase))
    .sort((left, right) => {
      if (right.z !== left.z) {
        return right.z - left.z;
      }
      return left.jobIndex - right.jobIndex;
    });
}

function canEnterRoad(runtime) {
  const minZ = runtime.layout.entryZ + runtime.road.entrySpacing;
  return runtime.truckActors.every((actor) => {
    if (!actor.visible || !PHASES_USING_LANE.has(actor.phase)) {
      return true;
    }
    return actor.z >= minZ;
  });
}

function bayOccupantConflict(runtime, actor) {
  return runtime.truckActors.some((other) => {
    if (other === actor || !other.visible || !PHASES_OCCUPYING_BAY.has(other.phase)) {
      return false;
    }
    return Math.abs(other.z - actor.slotZ) < runtime.road.bayClearance;
  });
}

function laneWindowClear(runtime, zCenter, behindDistance, aheadDistance, ignoredActor = null) {
  return runtime.truckActors.every((actor) => {
    if (actor === ignoredActor || !actor.visible || !PHASES_USING_LANE.has(actor.phase)) {
      return true;
    }
    if (actor.z >= zCenter) {
      return actor.z - zCenter >= aheadDistance;
    }
    return zCenter - actor.z >= behindDistance;
  });
}

function canStartParking(runtime, actor) {
  return !bayOccupantConflict(runtime, actor)
    && laneWindowClear(runtime, actor.slotZ, runtime.road.stopDistance, runtime.road.stopDistance * 0.7, actor);
}

function canStartMergeOut(runtime, actor) {
  return !bayOccupantConflict(runtime, actor)
    && laneWindowClear(runtime, actor.slotZ, runtime.road.mergeClearanceBehind, runtime.road.mergeClearanceAhead, actor);
}

function spawnReadyTrucks(runtime, time, hooks) {
  for (const actor of runtime.truckActors) {
    if (actor.phase !== DAY_TRUCK_PHASES.scheduled) {
      continue;
    }
    if (time + 1e-6 < actor.job.arrivalTime) {
      continue;
    }
    if (!canEnterRoad(runtime)) {
      break;
    }
    actor.visible = true;
    actor.x = runtime.layout.passingLaneX;
    actor.z = runtime.layout.entryZ;
    actor.heading = 0;
    actor.speed = actor.nominalRoadSpeed * 0.55;
    notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.enteringRoad, time, hooks);
  }
}

function targetRoadZForActor(runtime, actor) {
  if (actor.phase === DAY_TRUCK_PHASES.departing) {
    return runtime.layout.exitZ;
  }
  if (actor.phase === DAY_TRUCK_PHASES.mergingOut) {
    return actor.z;
  }
  return actor.holdZ;
}

function updateLaneTraffic(runtime, dt, time, hooks) {
  const laneActors = getLaneActors(runtime);
  for (let index = 0; index < laneActors.length; index += 1) {
    const actor = laneActors[index];
    const lead = index === 0 ? null : laneActors[index - 1];
    const targetZ = targetRoadZForActor(runtime, actor);
    const remainingDistance = Math.max(0, targetZ - actor.z);
    let desiredSpeed = actor.phase === DAY_TRUCK_PHASES.mergingOut ? 0 : actor.nominalRoadSpeed;

    if (remainingDistance <= 0.03) {
      desiredSpeed = 0;
    }

    if (lead) {
      const leadDistance = lead.z - actor.z - runtime.road.truckLength;
      if (leadDistance <= runtime.road.stopDistance) {
        desiredSpeed = 0;
      } else if (leadDistance < runtime.road.brakingDistance) {
        const ratio = (leadDistance - runtime.road.stopDistance)
          / (runtime.road.brakingDistance - runtime.road.stopDistance);
        desiredSpeed = Math.min(desiredSpeed, actor.nominalRoadSpeed * clamp01(ratio));
      }
    }

    const maxDelta = (desiredSpeed >= actor.speed ? runtime.road.roadAcceleration : runtime.road.roadBraking) * dt;
    actor.speed = moveTowards(actor.speed, desiredSpeed, maxDelta);
    if (actor.speed <= 0) {
      actor.speed = 0;
    }

    const travel = Math.min(remainingDistance, actor.speed * dt);
    actor.z += travel;
    actor.x = runtime.layout.passingLaneX;
    actor.heading = 0;

    if (
      actor.phase === DAY_TRUCK_PHASES.enteringRoad
      && actor.z - runtime.layout.entryZ >= runtime.road.entryProgressDistance
    ) {
      notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.drivingToParkingBay, time, hooks);
    }

    if (
      actor.phase === DAY_TRUCK_PHASES.drivingToParkingBay
      && actor.z >= actor.holdZ - 0.02
      && canStartParking(runtime, actor)
    ) {
      startManeuver(runtime, actor, DAY_TRUCK_PHASES.parkingBay, time, {
        duration: runtime.road.parkingDuration,
        endX: runtime.layout.parkingLaneX,
        endZ: actor.slotZ,
        endHeading: 0.22,
        completePhase: DAY_TRUCK_PHASES.waiting,
      }, hooks);
    }

    if (actor.phase === DAY_TRUCK_PHASES.departing && actor.z >= runtime.layout.exitZ - 0.02) {
      actor.visible = false;
      actor.speed = 0;
      actor.heading = 0;
      notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.finished, time, hooks);
      if (hooks?.onTruckFinished) {
        hooks.onTruckFinished(actor, time, runtime);
      }
    }
  }
}

function updateManeuvers(runtime, time, hooks) {
  for (const actor of runtime.truckActors) {
    if (!actor.maneuver) {
      continue;
    }
    const maneuver = actor.maneuver;
    const t = clamp01((time - maneuver.startTime) / maneuver.duration);
    const eased = easeInOutCubic(t);
    actor.x = lerp(maneuver.startX, maneuver.endX, eased);
    actor.z = lerp(maneuver.startZ, maneuver.endZ, eased);
    actor.heading = lerp(maneuver.startHeading, maneuver.endHeading, eased);
    actor.speed = 0;

    if (t < 1) {
      continue;
    }

    actor.x = maneuver.endX;
    actor.z = maneuver.endZ;
    actor.heading = maneuver.endHeading;
    actor.maneuver = null;

    if (maneuver.completePhase === DAY_TRUCK_PHASES.waiting) {
      actor.heading = 0;
      actor.parkedAt = time;
      notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.waiting, time, hooks);
    } else if (maneuver.completePhase === DAY_TRUCK_PHASES.departing) {
      actor.heading = 0;
      notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.departing, time, hooks);
    }
  }
}

function setCranePose(runtime, pose) {
  runtime.crane.pose.x = pose.x;
  runtime.crane.pose.z = pose.z;
  runtime.crane.pose.hookY = pose.hookY;
}

function interpolatePose(fromPose, toPose, value) {
  return {
    x: lerp(fromPose.x, toPose.x, value),
    z: lerp(fromPose.z, toPose.z, value),
    hookY: lerp(fromPose.hookY, toPose.hookY, value),
  };
}

function startCraneJob(runtime, actor, time, hooks) {
  const startTime = Math.max(time, Number(actor.job.loadStartTime) || 0);
  const plan = hooks?.buildCranePlan ? hooks.buildCranePlan(actor, startTime, runtime.crane.pose, runtime) : null;
  if (!plan) {
    return false;
  }
  runtime.crane.phase = DAY_CRANE_PHASES.executing;
  runtime.crane.activeActorKey = actor.key;
  runtime.crane.plan = plan;
  runtime.crane.pickupApplied = false;
  runtime.crane.dropApplied = false;
  runtime.crane.completedApplied = false;
  runtime.schedule.activeJobIndex = actor.jobIndex;
  notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.loading, startTime, hooks);
  if (hooks?.onCraneJobStart) {
    hooks.onCraneJobStart(actor, startTime, runtime);
  }
  return true;
}

function updateCrane(runtime, time, hooks) {
  if (runtime.crane.phase === DAY_CRANE_PHASES.idle) {
    const nextActor = runtime.truckActors[runtime.schedule.nextJobIndex] || null;
    if (
      nextActor
      && nextActor.phase === DAY_TRUCK_PHASES.waiting
      && time + 1e-6 >= (Number(nextActor.job.loadStartTime) || 0)
    ) {
      startCraneJob(runtime, nextActor, time, hooks);
    } else {
      runtime.schedule.activeJobIndex = -1;
    }
  }

  if (runtime.crane.phase !== DAY_CRANE_PHASES.executing || !runtime.crane.plan) {
    return;
  }

  const { plan } = runtime.crane;
  const actor = runtime.truckActors.find((candidate) => candidate.key === runtime.crane.activeActorKey);
  if (!actor) {
    runtime.crane.phase = DAY_CRANE_PHASES.idle;
    runtime.crane.plan = null;
    runtime.schedule.activeJobIndex = -1;
    return;
  }

  if (!runtime.crane.pickupApplied && time + 1e-6 >= plan.pickupTime) {
    runtime.crane.pickupApplied = true;
    if (hooks?.onCranePickup) {
      hooks.onCranePickup(actor, plan.pickupTime, runtime);
    }
  }

  if (!runtime.crane.dropApplied && time + 1e-6 >= plan.dropTime) {
    runtime.crane.dropApplied = true;
    if (hooks?.onCraneDrop) {
      hooks.onCraneDrop(actor, plan.dropTime, runtime);
    }
  }

  const activeSegment = plan.segments.find((segment) => time <= segment.end + 1e-6) || null;
  if (activeSegment) {
    const localT = activeSegment.end <= activeSegment.start
      ? 1
      : clamp01((time - activeSegment.start) / (activeSegment.end - activeSegment.start));
    setCranePose(runtime, interpolatePose(activeSegment.fromPose, activeSegment.toPose, localT));
  } else if (plan.finalPose) {
    setCranePose(runtime, plan.finalPose);
  }

  if (!runtime.crane.completedApplied && time + 1e-6 >= plan.endTime) {
    runtime.crane.completedApplied = true;
    runtime.crane.phase = DAY_CRANE_PHASES.idle;
    runtime.crane.plan = null;
    runtime.crane.activeActorKey = null;
    actor.loadedAt = plan.endTime;
    actor.departureReadyAt = Math.max(actor.departureReadyAt, plan.endTime);
    notifyPhaseChange(runtime, actor, DAY_TRUCK_PHASES.loaded, plan.endTime, hooks);
    runtime.schedule.nextJobIndex = Math.max(runtime.schedule.nextJobIndex, actor.jobIndex + 1);
    runtime.schedule.activeJobIndex = -1;
    runtime.schedule.completedJobs += 1;
    if (hooks?.onCraneJobComplete) {
      hooks.onCraneJobComplete(actor, plan.endTime, runtime);
    }
  }
}

function startDepartures(runtime, time, hooks) {
  for (const actor of runtime.truckActors) {
    if (actor.phase !== DAY_TRUCK_PHASES.loaded) {
      continue;
    }
    if (time + 1e-6 < actor.departureReadyAt) {
      continue;
    }
    if (!canStartMergeOut(runtime, actor)) {
      continue;
    }
    startManeuver(runtime, actor, DAY_TRUCK_PHASES.mergingOut, time, {
      duration: runtime.road.mergeDuration,
      endX: runtime.layout.passingLaneX,
      endZ: actor.slotZ + runtime.road.mergeAdvanceDistance,
      endHeading: -0.24,
      completePhase: DAY_TRUCK_PHASES.departing,
    }, hooks);
  }
}

function syncCompletion(runtime) {
  const allJobsCompleted = runtime.schedule.completedJobs >= runtime.truckActors.length;
  const allTrucksFinished = runtime.truckActors.every((actor) => {
    return actor.phase === DAY_TRUCK_PHASES.finished || actor.phase === DAY_TRUCK_PHASES.scheduled;
  });
  runtime.completed = allJobsCompleted && allTrucksFinished;
}

export function createDayRuntime(dayCycle, config = {}) {
  const jobs = dayCycle?.jobs || [];
  const layout = {
    entryZ: Number(config.entryZ) || 0,
    exitZ: Number(config.exitZ) || 0,
    passingLaneX: Number(config.passingLaneX) || 0,
    parkingLaneX: Number(config.parkingLaneX) || 0,
    slotZ: Array.isArray(config.slotZ) ? config.slotZ.map((value) => Number(value) || 0) : [],
  };
  const road = {
    fixedStepSeconds: Number(config.fixedStepSeconds) || DEFAULTS.fixedStepSeconds,
    maxFixedStepsPerFrame: Number(config.maxFixedStepsPerFrame) || DEFAULTS.maxFixedStepsPerFrame,
    entryProgressDistance: Number(config.entryProgressDistance) || DEFAULTS.entryProgressDistance,
    approachBuffer: Number(config.approachBuffer) || DEFAULTS.approachBuffer,
    nominalRoadSpeed: Number(config.nominalRoadSpeed) || DEFAULTS.nominalRoadSpeed,
    roadAcceleration: Number(config.roadAcceleration) || DEFAULTS.roadAcceleration,
    roadBraking: Number(config.roadBraking) || DEFAULTS.roadBraking,
    stopDistance: Number(config.stopDistance) || DEFAULTS.stopDistance,
    brakingDistance: Number(config.brakingDistance) || DEFAULTS.brakingDistance,
    truckLength: Number(config.truckLength) || DEFAULTS.truckLength,
    bayClearance: Number(config.bayClearance) || DEFAULTS.bayClearance,
    entrySpacing: Number(config.entrySpacing) || DEFAULTS.entrySpacing,
    mergeClearanceAhead: Number(config.mergeClearanceAhead) || DEFAULTS.mergeClearanceAhead,
    mergeClearanceBehind: Number(config.mergeClearanceBehind) || DEFAULTS.mergeClearanceBehind,
    parkingDuration: Number(config.parkingDuration) || DEFAULTS.parkingDuration,
    mergeDuration: Number(config.mergeDuration) || DEFAULTS.mergeDuration,
    mergeAdvanceDistance: Number(config.mergeAdvanceDistance) || DEFAULTS.mergeAdvanceDistance,
  };

  return {
    jobs,
    layout,
    road,
    truckActors: jobs.map((job, index) => createTruckActor(job, index, layout, road)),
    crane: {
      phase: DAY_CRANE_PHASES.idle,
      pose: {
        x: Number(config.initialCranePose?.x) || 0,
        z: Number(config.initialCranePose?.z) || 0,
        hookY: Number(config.initialCranePose?.hookY) || 0,
      },
      activeActorKey: null,
      plan: null,
      pickupApplied: false,
      dropApplied: false,
      completedApplied: false,
    },
    schedule: {
      nextJobIndex: 0,
      completedJobs: 0,
      activeJobIndex: -1,
    },
    lastSimTime: 0,
    completed: jobs.length === 0,
    statusText: "",
  };
}

export function advanceDayRuntime(runtime, targetTime, hooks = {}) {
  if (!runtime) {
    return;
  }

  const safeTarget = Math.max(runtime.lastSimTime, Number(targetTime) || 0);
  let cursor = runtime.lastSimTime;
  const backlog = safeTarget - runtime.lastSimTime;
  const dynamicStep = backlog <= runtime.road.fixedStepSeconds * runtime.road.maxFixedStepsPerFrame
    ? runtime.road.fixedStepSeconds
    : backlog / runtime.road.maxFixedStepsPerFrame;
  let steps = 0;

  while (cursor + 1e-6 < safeTarget && steps < runtime.road.maxFixedStepsPerFrame) {
    const nextTime = Math.min(safeTarget, cursor + dynamicStep);
    const dt = nextTime - cursor;
    spawnReadyTrucks(runtime, nextTime, hooks);
    updateManeuvers(runtime, nextTime, hooks);
    updateLaneTraffic(runtime, dt, nextTime, hooks);
    updateCrane(runtime, nextTime, hooks);
    startDepartures(runtime, nextTime, hooks);
    syncCompletion(runtime);
    cursor = nextTime;
    steps += 1;
  }

  runtime.lastSimTime = safeTarget;
}

export function dayRuntimeHasActiveActors(runtime) {
  if (!runtime) {
    return false;
  }
  return runtime.truckActors.some((actor) => actor.visible) || runtime.crane.phase !== DAY_CRANE_PHASES.idle;
}

export function getTruckPhaseOrderValue(phase) {
  return phaseOrderValue(phase);
}

export { DAY_CRANE_PHASES, DAY_TRUCK_PHASES };
