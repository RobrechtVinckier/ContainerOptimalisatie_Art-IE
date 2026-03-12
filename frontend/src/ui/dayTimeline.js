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

function groupJobsByCompany(jobs) {
  const grouped = new Map();
  for (const job of sortJobsBySchedule(jobs)) {
    const key = `${job.company}|${job.companyColor || job.containerColor || ""}`;
    let entry = grouped.get(key);
    if (!entry) {
      entry = {
        key,
        company: job.company,
        color: job.companyColor || job.containerColor || "#5c7fa6",
        jobs: [],
        firstArrival: job.arrivalTime,
      };
      grouped.set(key, entry);
    }
    entry.jobs.push(job);
    entry.firstArrival = Math.min(entry.firstArrival, job.arrivalTime);
  }
  return [...grouped.values()].sort((left, right) => {
    if (left.firstArrival !== right.firstArrival) {
      return left.firstArrival - right.firstArrival;
    }
    return left.company.localeCompare(right.company);
  });
}

function compactTruckLabel(label) {
  return String(label).replace("Truck #", "#").replace("Truck ", "");
}

function appendSummary(host, jobs, groups, currentTimeSeconds, dayStartSeconds) {
  const summary = document.createElement("div");
  summary.className = "timeline-summary";

  const planned = document.createElement("span");
  planned.textContent = `${jobs.length} planned truck${jobs.length === 1 ? "" : "s"}`;
  summary.appendChild(planned);

  const companies = document.createElement("span");
  companies.textContent = `${groups.length} compan${groups.length === 1 ? "y" : "ies"}`;
  summary.appendChild(companies);

  const mode = document.createElement("span");
  mode.textContent = "Timeline is the primary day-flow view";
  summary.appendChild(mode);

  if (Number.isFinite(currentTimeSeconds)) {
    const current = document.createElement("strong");
    current.className = "timeline-summary-current";
    current.textContent = `Current ${formatTime(currentTimeSeconds, dayStartSeconds)}`;
    summary.appendChild(current);
  }

  host.appendChild(summary);
}

function appendAxis(host, dayDurationSeconds, dayStartSeconds) {
  const axis = document.createElement("div");
  axis.className = "timeline-axis";

  const gutter = document.createElement("div");
  gutter.className = "timeline-axis-gutter";
  gutter.textContent = "Company";
  axis.appendChild(gutter);

  const track = document.createElement("div");
  track.className = "timeline-axis-track";
  const tickCount = 9;
  for (let index = 0; index < tickCount; index += 1) {
    const tickSeconds = (dayDurationSeconds / (tickCount - 1)) * index;
    const tick = document.createElement("span");
    tick.className = "timeline-axis-tick";
    tick.style.left = `${clampPercent((tickSeconds / dayDurationSeconds) * 100)}%`;
    tick.textContent = formatTime(tickSeconds, dayStartSeconds);
    track.appendChild(tick);
  }
  axis.appendChild(track);
  host.appendChild(axis);
}

function appendCurrentTimeLine(track, currentTimeSeconds, dayDurationSeconds) {
  if (!Number.isFinite(currentTimeSeconds)) {
    return;
  }
  const line = document.createElement("div");
  line.className = "timeline-current-line";
  line.style.left = `${clampPercent((currentTimeSeconds / dayDurationSeconds) * 100)}%`;
  track.appendChild(line);
}

function renderGroupRow(group, host, options) {
  const {
    activeJobIndex,
    currentTimeSeconds,
    dayDurationSeconds,
    dayStartSeconds,
    formatTruckLabel,
  } = options;
  const row = document.createElement("section");
  row.className = "timeline-row";

  const label = document.createElement("div");
  label.className = "timeline-row-label";
  const swatch = document.createElement("span");
  swatch.className = "timeline-row-swatch";
  swatch.style.background = group.color;
  label.appendChild(swatch);

  const meta = document.createElement("div");
  meta.className = "timeline-row-meta";
  const company = document.createElement("strong");
  company.textContent = group.company;
  meta.appendChild(company);

  const count = document.createElement("span");
  count.textContent = `${group.jobs.length} truck${group.jobs.length === 1 ? "" : "s"}`;
  meta.appendChild(count);
  label.appendChild(meta);
  row.appendChild(label);

  const track = document.createElement("div");
  track.className = "timeline-row-track";
  const assignedJobs = assignJobLanes(group.jobs);
  const laneCount = Math.max(1, ...assignedJobs.map((item) => item.laneIndex + 1));
  track.style.setProperty("--timeline-track-lanes", String(laneCount));
  appendCurrentTimeLine(track, currentTimeSeconds, dayDurationSeconds);

  for (const { job, laneIndex } of assignedJobs) {
    const startPercent = clampPercent((job.arrivalTime / dayDurationSeconds) * 100);
    const widthPercent = Math.max(0.3, clampPercent(((job.departTime - job.arrivalTime) / dayDurationSeconds) * 100));
    const block = document.createElement("article");
    block.className = "timeline-job";
    if (job.jobIndex - 1 === activeJobIndex) {
      block.classList.add("is-active");
    }
    if (widthPercent <= 1.2) {
      block.classList.add("is-micro");
    } else if (widthPercent <= 2.6) {
      block.classList.add("is-compact");
    }
    block.style.left = `${startPercent}%`;
    block.style.width = `${widthPercent}%`;
    block.style.top = `calc(${laneIndex} * (var(--timeline-track-row-height) + 6px) + 4px)`;
    block.style.background = group.color;
    block.title = `${formatTruckLabel(job.truckId)} | ${job.company} | ${formatTime(job.arrivalTime, dayStartSeconds)}-${formatTime(job.departTime, dayStartSeconds)}`;

    const truck = document.createElement("strong");
    const fullLabel = formatTruckLabel(job.truckId);
    truck.textContent = widthPercent <= 2.6 ? compactTruckLabel(fullLabel) : fullLabel;
    block.appendChild(truck);

    if (widthPercent > 1.2) {
      const jobMeta = document.createElement("span");
      jobMeta.textContent = widthPercent <= 3.2
        ? formatTime(job.arrivalTime, dayStartSeconds)
        : `${formatTime(job.arrivalTime, dayStartSeconds)} • ${job.company}`;
      block.appendChild(jobMeta);
    }

    track.appendChild(block);
  }

  row.appendChild(track);
  host.appendChild(row);
}

export function renderDayTimeline(host, dayCycle, options = {}) {
  const activeJobIndex = Number.isFinite(options.activeJobIndex) ? Number(options.activeJobIndex) : -1;
  const currentTimeSeconds = Number.isFinite(options.currentTimeSeconds) ? Number(options.currentTimeSeconds) : null;
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
  const groups = groupJobsByCompany(jobs);
  appendSummary(timeline, jobs, groups, currentTimeSeconds, dayStartSeconds);
  appendAxis(timeline, dayDurationSeconds, dayStartSeconds);
  const rows = document.createElement("div");
  rows.className = "timeline-rows";
  for (const group of groups) {
    renderGroupRow(group, rows, {
      activeJobIndex,
      currentTimeSeconds,
      dayDurationSeconds,
      dayStartSeconds,
      formatTruckLabel,
    });
  }

  timeline.appendChild(rows);
  host.appendChild(timeline);
}
