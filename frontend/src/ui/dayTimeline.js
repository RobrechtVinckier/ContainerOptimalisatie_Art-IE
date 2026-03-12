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

function assignJobLanes(jobs) {
  const laneEndTimes = [];
  return jobs.map((job) => {
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
    const block = document.createElement("article");
    block.className = "timeline-block";
    if (job.jobIndex - 1 === activeJobIndex) {
      block.classList.add("is-active");
    }
    block.style.left = `${clampPercent((job.arrivalTime / dayDurationSeconds) * 100)}%`;
    block.style.width = `${Math.max(4, clampPercent(((job.departTime - job.arrivalTime) / dayDurationSeconds) * 100))}%`;
    block.style.top = `calc(${laneIndex} * (var(--timeline-row-height) + 8px))`;
    block.style.background = job.companyColor || "#5c7fa6";
    block.title = `${formatTruckLabel(job.truckId)} | ${job.company} | ${formatTime(job.arrivalTime, dayStartSeconds)}-${formatTime(job.departTime, dayStartSeconds)}`;

    const truck = document.createElement("strong");
    truck.textContent = formatTruckLabel(job.truckId);
    block.appendChild(truck);

    const meta = document.createElement("span");
    meta.textContent = `${job.company} • ${formatTime(job.arrivalTime, dayStartSeconds)}`;
    block.appendChild(meta);

    body.appendChild(block);
  }

  timeline.appendChild(body);
  host.appendChild(timeline);
}
