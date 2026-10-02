/**
 * 렌더 — 이 파일이 Python↔Node 경계 전부다.
 *
 *   node scripts/render.mjs --dir <컴포지션폴더> --out <out.mp4> [--fps 30]
 *                           [--quality standard] [--workers 6]
 *
 * ★ stdout 에 **태그 줄**을 흘린다. Python(`pipeline/s6_render.py`)이 이것만 읽는다.
 *   260721-compiui-short/app/render.py 가 이미 쓰는 규약을 그대로 따른다.
 *
 *     [stage] <이름>
 *     [progress] <0..100> <메시지>
 *     [warn] <내용>
 *     [perf] <JSON>
 *     [done] <출력경로>
 *     [error] <내용>
 *
 * ★ `executeRenderJob` 은 Promise<void> 다. 결과는 **넘긴 job 객체를 변형**해서
 *   돌려준다(outputPath · outcome · warnings · perfSummary). 참조를 붙들어야 한다.
 *
 * ★ @hyperframes/* 는 전부 ESM 이다. 그래서 이 파일이 .mjs 다.
 */
import { createRenderJob, executeRenderJob } from "@hyperframes/producer";
import { resolve } from "node:path";

function arg(name, dflt = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : dflt;
}

const dir = arg("dir");
const out = arg("out");
if (!dir || !out) {
  console.log("[error] --dir 와 --out 이 필요합니다.");
  process.exit(2);
}

const fps = Number(arg("fps", "30"));
const quality = arg("quality", "standard");
const workers = Number(arg("workers", "0"));

const config = { fps, quality, format: "mp4" };
// 0 이면 넘기지 않는다 — HyperFrames 가 코어·메모리·프레임 수로 알아서 정한다
if (workers > 0) config.workers = workers;

const job = createRenderJob(config);

let lastPct = -1;
let lastStage = "";

/** 진행률은 촘촘히 오는데 그대로 흘리면 로그가 수천 줄이 된다. 1% 단위로만. */
function onProgress(j, message) {
  // ★ currentStage 에 프레임 수가 들어온다("Capturing frame 4530/4571") — 그대로
  //   비교하면 프레임마다 새 단계로 보여 로그가 수백 줄이 된다. 숫자를 지운 뒤 비교한다.
  const stageName = (j.currentStage ?? "").replace(/\d+/g, "").trim();
  if (stageName && stageName !== lastStage) {
    lastStage = stageName;
    console.log(`[stage] ${j.currentStage}`);
  }
  const pct = Math.round(j.progress ?? 0);
  if (pct !== lastPct) {
    lastPct = pct;
    console.log(`[progress] ${pct} ${message ?? ""}`.trimEnd());
  }
}

try {
  await executeRenderJob(job, resolve(dir), resolve(out), onProgress);

  for (const w of job.warnings ?? []) {
    console.log(`[warn] ${typeof w === "string" ? w : JSON.stringify(w)}`);
  }
  if (job.perfSummary) {
    // 렌더 단가 모델의 재료다 — 실측 없이는 예상 시간을 말할 수 없다
    const p = job.perfSummary;
    console.log(`[perf] ${JSON.stringify({
      totalElapsedMs: p.totalElapsedMs,
      captureP50Ms: p.captureP50Ms,
      peakRssMb: p.peakRssMb,
      staticDedup: p.staticDedup,
      workerSizing: p.workerSizing,
      totalFrames: job.totalFrames,
    })}`);
  }
  if (job.outcome === "failed" || job.status === "failed") {
    console.log(`[error] ${job.error ?? "렌더 실패"}`);
    process.exit(1);
  }
  console.log(`[done] ${job.outputPath ?? resolve(out)}`);
  process.exit(0);
} catch (e) {
  console.log(`[error] ${e?.stack ?? e?.message ?? String(e)}`);
  process.exit(1);
}
