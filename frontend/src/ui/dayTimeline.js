function clampPercent(value) {
  return Math.max(0, Math.min(100, value));
}

function formatTime(secondsSinceDayStart, dayStartSeconds) {
  const absoluteSeconds = dayStartSeconds + Math.max(0, Math.floor(Number(secondsSinceDayStart) || 0));
  const normalized = ((absoluteSeconds % 86400) + 86400) % 86400;
  const hours = String(Math.floor(normalized / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((normalized % 3600) / 60)).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function sortJobsBySchedule(jobs) {
  return [...jobs].sort((left, right) => {
    if (left.arrivalTime !== right.arrivalTime) {
      return left.arrivalTime - right.arrivalTime;
    }
    if (left.departTime !== right.departTime) {
      return left.departTime - right.departTime;
    }
    return (left.jobIndex || 0) - (right.jobIndex || 0);
  });
}

function assignJobLanes(jobs) {
  const laneEndTimes = [];
  return sortJobsBySchedule(jobs).map((job) => {
    let laneIndex = laneEndTimes.findIndex((endTime) => endTime <= job.arrivalTime);
    if (laneIndex === -1) {
      laneIndex = laneEndTimes.length;
      laneEndTimes.push(job.departTime);
    } else {
      laneEndTimes[laneIndex] = job.departTime;
    }
    return { job, laneIndex };
  });
}

export function renderDayTimeline(host, dayCycle, options = {}) {
  const activeJobIndex = Number.isFinite(options.activeJobIndex) ? Number(options.activeJobIndex) : -1;
  const formatTruckLabel = typeof options.formatTruckLabel === "function"
    ? options.formatTruckLabel
    : (truckId) => String(truckId);

  host.textContent = "";

  const jobs = dayCycle?.jobs || [];
  const stats = dayCycle?.stats || {};
  const dayDurationSeconds = Math.max(1, Number(stats.dayDurationSeconds) || 1);
  const dayStartSeconds = Number(stats.dayStartSeconds) || 0;

  if (!jobs.length) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    empty.textContent = "No truck jobs scheduled yet.";
    host.appendChild(empty);
    return;
  }

  const timeline = document.createElement("div");
  timeline.className = "timeline-chart";

  const axis = document.createElement("div");
  axis.className = "timeline-axis";
  const tickCount = 5;
  for (let index = 0; index < tickCount; index += 1) {
    const tickSeconds = (dayDurationSeconds / (tickCount - 1)) * index;
    const tick = document.createElement("span");
    tick.style.left = `${clampPercent((tickSeconds / dayDurationSeconds) * 100)}%`;
    tick.textContent = formatTime(tickSeconds, dayStartSeconds);
    axis.appendChild(tick);
  }
  timeline.appendChild(axis);

  const body = document.createElement("div");
  body.className = "timeline-body";
  const assignedJobs = assignJobLanes(jobs);
  const laneCount = Math.max(...assignedJobs.map((item) => item.laneIndex)) + 1;
  body.style.setProperty("--timeline-lanes", String(laneCount));

  for (const { job, laneIndex } of assignedJobs) {
    const startPercent = clampPercent((job.arrivalTime / dayDurationSeconds) * 100);
    const widthPercent = Math.max(0.55, clampPercent(((job.departTime - job.arrivalTime) / dayDurationSeconds) * 100));
    const visualColor = job.companyColor || job.containerColor || "#5c7fa6";
    const compactTruckLabel = formatTruckLabel(job.truckId).replace("Truck #", "#");
    const block = document.createElement("article");
    block.className = "timeline-block";
    if (job.jobIndex - 1 === activeJobIndex) {
      block.classList.add("is-active");
    }
    if (widthPercent <= 2.1) {
      block.classList.add("is-micro");
    } else if (widthPercent <= 4.2) {
      block.classList.add("is-compact");
    }
    block.style.left = `${startPercent}%`;
    block.style.width = `${widthPercent}%`;
    block.style.top = `calc(${laneIndex} * (var(--timeline-row-height) + 8px))`;
    block.style.background = visualColor;
    block.title = `${formatTruckLabel(job.truckId)} | ${job.company} | ${formatTime(job.arrivalTime, dayStartSeconds)}-${formatTime(job.departTime, dayStartSeconds)}`;

    const truck = document.createElement("strong");
    truck.textContent = widthPercent <= 2.1 ? compactTruckLabel : formatTruckLabel(job.truckId);
    block.appendChild(truck);

    if (widthPercent > 2.1) {
      const meta = document.createElement("span");
      meta.textContent = widthPercent <= 4.2
        ? formatTime(job.arrivalTime, dayStartSeconds)
        : `${job.company} • ${formatTime(job.arrivalTime, dayStartSeconds)}`;
      block.appendChild(meta);
    }

    body.appendChild(block);
  }

  timeline.appendChild(body);
  host.appendChild(timeline);
}
