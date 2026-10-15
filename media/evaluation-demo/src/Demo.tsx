import React from "react";
import {
  AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
} from "remotion";
import data from "../public/data.json";
import meta from "../public/manim/meta.json";
import { INK, KIND, LINE, MONO, MUTED, NAVY, NODE_EDGE, NODE_FILL, PAPER, SANS, VERDICT } from "./theme";
import { AgentIcon, JudgeIcon, UserAvatar } from "./Icons";
import { Results, RESULTS_FRAMES } from "./Results";

export const FPS = 30;
const S = (s: number) => Math.round(s * FPS);

// ---------------------------------------------------------------- timeline (frames)
const INTRO = meta.timeline;
const BEATS = [
  { bubble: S(4), agent: S(7), app: S(3), judge: S(6.5), tick: S(1) },
  { bubble: S(3.5), agent: S(5), app: S(2.5), judge: S(6), tick: S(1) },
  { bubble: S(3.5), agent: S(5), app: S(2.5), judge: S(6.5), tick: S(1) },
];
const beatLen = (b: (typeof BEATS)[number]) => b.bubble + b.agent + b.app + b.judge + b.tick;
const FAST = S(4);
const FINALE = meta.sweep;
export const DEMO_FRAMES = INTRO + BEATS.reduce((a, b) => a + beatLen(b), 0) + FAST + FINALE + RESULTS_FRAMES;

const MANIM_FPS = 30;
const manimFrame = (clip: string, local: number, total: number) =>
  staticFile(`manim/${clip}/${String(Math.min(Math.max(local, 0), total - 1) + 1).padStart(4, "0")}.png`);

// ---------------------------------------------------------------- small pieces
const typed = (text: string, frame: number, cps = 1.6) => text.slice(0, Math.max(0, Math.floor(frame * cps)));

const Caption: React.FC<{ children: React.ReactNode; frame: number }> = ({ children, frame }) => (
  <div
    style={{
      position: "absolute", left: 0, right: 0, bottom: 44, textAlign: "center", fontFamily: SANS,
      fontSize: 30, color: INK, opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }),
    }}
  >
    {children}
  </div>
);

const Header: React.FC<{ current: number; lit: number; accuracy: number[] }> = ({ current, lit, accuracy }) => (
  <div style={{ position: "absolute", top: 36, left: 80, right: 80, height: 110, fontFamily: SANS }}>
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      {Array.from({ length: 10 }, (_, i) => {
        const on = i < lit;
        const isCur = i === current;
        const acc = accuracy[i];
        return (
          <React.Fragment key={i}>
            <div
              style={{
                width: 128, height: 64, borderRadius: 12, border: `2.5px solid ${on || isCur ? NODE_EDGE[i % 5] : LINE}`,
                background: on || isCur ? NODE_FILL[i % 5] : "#fff", display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center", color: on || isCur ? NAVY : MUTED,
                boxShadow: isCur ? `0 0 0 5px ${NODE_EDGE[i % 5]}33` : "none", transition: "none",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 24 }}>R{i + 1}</div>
              <div style={{ fontSize: 16, fontVariantNumeric: "tabular-nums", color: INK, opacity: on ? 1 : 0 }}>
                {on ? `${acc.toFixed(0)}%` : "–"}
              </div>
            </div>
            {i < 9 && <div style={{ width: 22, height: 3, background: i < lit - 1 || i < current ? NAVY : LINE }} />}
          </React.Fragment>
        );
      })}
    </div>
  </div>
);

const Panel: React.FC<{ title: string; sub?: string; x: number; y: number; w: number; h: number; children?: React.ReactNode; accent?: string; enter: number; icon?: React.ReactNode }> =
  ({ title, sub, x, y, w, h, children, accent = NAVY, enter, icon }) => {
    const p = spring({ frame: enter, fps: FPS, config: { damping: 200, stiffness: 120 } });
    return (
      <div
        style={{
          position: "absolute", left: x, top: y + (1 - p) * 24, width: w, height: h, opacity: p,
          background: "#fff", border: `1.5px solid ${LINE}`, borderRadius: 16, boxShadow: "0 10px 30px rgba(31,58,95,0.08)",
          fontFamily: SANS, overflow: "hidden",
        }}
      >
        <div style={{ height: 54, borderBottom: `1px solid ${LINE}`, display: "flex", alignItems: "center", padding: "0 22px", gap: 12 }}>
          {icon ?? <div style={{ width: 12, height: 12, borderRadius: 6, background: accent }} />}
          <div style={{ fontWeight: 700, fontSize: 22, color: NAVY }}>{title}</div>
          {sub && <div style={{ fontSize: 18, color: MUTED }}>{sub}</div>}
        </div>
        <div style={{ position: "absolute", top: 55, left: 0, right: 0, bottom: 0 }}>{children}</div>
      </div>
    );
  };

// ---------------------------------------------------------------- beats
const Bubble: React.FC<{ req: (typeof data.requests)[number]; idx: number }> = ({ req, idx }) => {
  const frame = useCurrentFrame();
  const pop = spring({ frame, fps: FPS, config: { damping: 14, stiffness: 160 } });
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 300, top: 300, display: "flex", alignItems: "flex-start", gap: 28, transform: `scale(${0.9 + 0.1 * pop})`, transformOrigin: "left top", opacity: pop }}>
        <UserAvatar size={96} />
        <div style={{ position: "relative", width: 1080, background: "#fff", border: `2px solid ${NAVY}`, borderRadius: 22, padding: "26px 34px", fontFamily: SANS, fontSize: 34, lineHeight: 1.35, color: INK, minHeight: 150 }}>
          <div style={{ position: "absolute", left: -16, top: 34, width: 26, height: 26, background: "#fff", borderLeft: `2px solid ${NAVY}`, borderBottom: `2px solid ${NAVY}`, transform: "rotate(45deg)" }} />
          <div style={{ fontSize: 20, color: MUTED, marginBottom: 8, letterSpacing: 1 }}>
            REQUEST {req.id.slice(1)} OF 10 · {req.label.toUpperCase()}
          </div>
          {typed(req.text, frame - 8, 1.7)}
          <span style={{ opacity: Math.floor(frame / 8) % 2 ? 0 : 1 }}>▍</span>
        </div>
      </div>
      <Caption frame={frame - 20}>{idx === 0 ? "A user asks for a web app. The coding agent builds it." : "The same user comes back and asks for more. The agent extends the running app."}</Caption>
    </AbsoluteFill>
  );
};

const Agent: React.FC<{ req: (typeof data.requests)[number]; dur: number }> = ({ req, dur }) => {
  const frame = useCurrentFrame();
  const calls = req.calls.slice(0, 11);
  const per = (dur - S(1.6)) / (calls.length + 1);
  const shown = Math.min(calls.length, Math.floor(frame / per));
  const buildAt = per * (calls.length + 0.5);
  const lines = calls.slice(0, shown);
  const visible = lines.slice(-8);
  return (
    <AbsoluteFill>
      <Panel title="Coding agent" sub={`OpenHands · ${data.model}`} x={160} y={200} w={1600} h={620} enter={frame} accent="#2f5f8f" icon={<AgentIcon size={34} />}>
        <div style={{ position: "absolute", inset: 0, background: "#0f1b2d", color: "#d6e2f0", fontFamily: MONO, fontSize: 25, padding: "22px 30px", lineHeight: 1.55 }}>
          <div style={{ color: "#7f93ad" }}>{"# request "}{req.id.slice(1)}{": the agent reads the workspace, edits the app, builds it"}</div>
          {visible.map((c, i) => (
            <div key={i} style={{ display: "flex", gap: 16, whiteSpace: "nowrap", overflow: "hidden" }}>
              <span style={{ color: c.kind === "edit" ? "#f2c879" : "#7fd1a8", width: 110, flexShrink: 0 }}>{c.kind === "edit" ? "✎ edit" : "▶ run"}</span>
              <span style={{ color: "#fff" }}>{c.title}</span>
              {c.arg && c.arg !== "create" && c.arg !== "str_replace" && <span style={{ color: "#7f93ad" }}>{c.arg}</span>}
            </div>
          ))}
          {frame > buildAt && (
            <div style={{ display: "flex", gap: 16 }}>
              <span style={{ color: "#7fd1a8", width: 110 }}>▶ run</span>
              <span style={{ color: "#fff" }}>npm run build</span>
              <span style={{ color: "#7fd1a8", opacity: interpolate(frame, [buildAt + 14, buildAt + 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
                ✓ built in 1.9s
              </span>
            </div>
          )}
          {frame <= buildAt && <span style={{ opacity: Math.floor(frame / 8) % 2 ? 0 : 1 }}>▍</span>}
        </div>
        <div style={{ position: "absolute", right: 26, bottom: 16, fontFamily: SANS, fontSize: 19, color: MUTED, display: "flex", alignItems: "center", gap: 10 }}>
          <AgentIcon size={28} color="#9fb3cc" /> {req.calls.length} tool calls in this request
        </div>
      </Panel>
      <Caption frame={frame - 10}>Tool calls from the real trajectory: shell commands and file edits, then a build.</Caption>
    </AbsoluteFill>
  );
};

const Browser: React.FC<{ src: string; x: number; y: number; w: number; label?: string; enter: number }> = ({ src, x, y, w, label, enter }) => {
  const p = spring({ frame: enter, fps: FPS, config: { damping: 200, stiffness: 120 } });
  const h = (w * 375) / 768;
  return (
    <div style={{ position: "absolute", left: x, top: y + (1 - p) * 30, width: w, opacity: p, borderRadius: 14, overflow: "hidden", border: `1.5px solid ${LINE}`, boxShadow: "0 14px 40px rgba(31,58,95,0.14)", background: "#fff" }}>
      <div style={{ height: 40, background: "#eef2f7", display: "flex", alignItems: "center", gap: 8, padding: "0 14px", fontFamily: SANS, fontSize: 16, color: MUTED }}>
        <span style={{ width: 12, height: 12, borderRadius: 6, background: "#e57373" }} />
        <span style={{ width: 12, height: 12, borderRadius: 6, background: "#f0c36d" }} />
        <span style={{ width: 12, height: 12, borderRadius: 6, background: "#8bc98f" }} />
        <span style={{ marginLeft: 14, background: "#fff", borderRadius: 6, padding: "3px 12px", flex: 1 }}>localhost:5173{label ? `  ·  ${label}` : ""}</span>
      </div>
      <Img src={staticFile(src)} style={{ width: w, height: h, display: "block" }} />
    </div>
  );
};

const AppRender: React.FC<{ req: (typeof data.requests)[number] }> = ({ req }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Browser src={req.app} x={330} y={190} w={1260} enter={frame} label={`after ${req.id}`} />
      <Caption frame={frame - 10}>The app as the judge will see it, served from the agent's build.</Caption>
    </AbsoluteFill>
  );
};

const Judge: React.FC<{ req: (typeof data.requests)[number]; dur: number }> = ({ req, dur }) => {
  const frame = useCurrentFrame();
  const steps = req.judge.steps;
  const stepDur = (dur - S(1.8)) / steps.length;
  const i = Math.min(steps.length - 1, Math.floor(frame / stepDur));
  const local = frame - i * stepDur;
  const step = steps[i];
  const last = i === steps.length - 1;
  const verdict = req.judge.verdict.toLowerCase();
  const verdictAt = steps.length * stepDur - S(0.4);
  const shownTask = req.checks.findIndex((c) => c.task === req.judge.task);
  const chipDone = (k: number) => (k === shownTask ? frame > verdictAt : frame > verdictAt + S(0.35) + k * 5);
  return (
    <AbsoluteFill>
      <Panel title="Browser agent evaluation" sub={`WebVoyager · ${data.judge}`} x={120} y={190} w={1680} h={640} enter={frame} accent="#3f8f5f" icon={<JudgeIcon size={34} />}>
        <div style={{ position: "absolute", left: 0, top: 0, width: 1010, height: 585, background: "#0b1626" }}>
          <div style={{ width: 1010, height: 493, overflow: "hidden" }}>
            <Img src={staticFile(step.shot)} style={{ width: 1010, height: 493, display: "block", objectFit: "cover", objectPosition: "top", transform: `scale(${1 + 0.02 * Math.min(1, local / stepDur)})`, transformOrigin: "50% 30%", opacity: interpolate(local, [0, 5], [0.5, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }} />
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 92, background: "#0b1626", color: "#d6e2f0", fontFamily: SANS, padding: "10px 22px", fontSize: 19, lineHeight: 1.35 }}>
            <span style={{ color: "#7f93ad", letterSpacing: 1, fontSize: 15 }}>JUDGE THINKS · step {step.step} of {step.of}</span>
            <div style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{typed(step.thought, local, 3.2)}</div>
          </div>
          <div style={{ position: "absolute", right: 18, top: 440, background: "#1f3a5f", color: "#fff", fontFamily: MONO, fontSize: 18, padding: "6px 12px", borderRadius: 8, opacity: interpolate(local, [stepDur * 0.55, stepDur * 0.7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
            {last && frame > verdictAt ? `ANSWER: ${req.judge.verdict}` : step.action}
          </div>
        </div>
        <div style={{ position: "absolute", left: 1010, top: 0, right: 0, bottom: 0, padding: "22px 28px", fontFamily: SANS }}>
          <div style={{ fontSize: 15, letterSpacing: 1, color: MUTED }}>CHECK UNDER TEST</div>
          <div style={{ fontSize: 21, color: INK, lineHeight: 1.35, marginTop: 6, minHeight: 120 }}>{req.judge.task}</div>
          <div style={{ fontSize: 15, letterSpacing: 1, color: MUTED, marginTop: 18 }}>
            {req.checks.length} CHECKS FOR THIS REQUEST
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 10 }}>
            {req.checks.map((c, k) => {
              const kind = KIND[c.kind] ?? KIND.feature;
              const done = chipDone(k);
              const v = VERDICT[c.verdict] ?? VERDICT.no;
              const isShown = k === shownTask;
              return (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 19, opacity: isShown || done ? 1 : 0.55 }}>
                  <div style={{ width: 10, height: 26, borderRadius: 3, background: kind.color }} />
                  <div style={{ width: 118, color: kind.color, fontWeight: 600 }}>{kind.label}</div>
                  <div style={{ flex: 1, color: INK, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontWeight: isShown ? 600 : 400 }}>{c.task}</div>
                  <div style={{ width: 34, height: 34, borderRadius: 17, background: done ? v.color : "#eef2f7", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 18 }}>
                    {done ? v.glyph : ""}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ position: "absolute", left: 28, right: 28, bottom: 18, fontSize: 24, fontWeight: 700, color: NAVY, opacity: frame > verdictAt + S(0.9) ? 1 : 0 }}>
            {req.accuracy.toFixed(0)}% of checks passed
          </div>
        </div>
      </Panel>
      <Caption frame={frame - 10}>
        {verdict === "no"
          ? "A real failure: the add-to-watchlist control is missing on this row, so the integration check fails."
          : "The browser agent sees the page with numbered elements, thinks, acts, and gives a verdict."}
      </Caption>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- fast forward and finale
const FastForward: React.FC = () => {
  const frame = useCurrentFrame();
  const n = Math.min(10, 3 + Math.floor(frame / (FAST / 9)));
  return (
    <AbsoluteFill>
      <Header current={Math.min(9, n - 1)} lit={n} accuracy={data.accuracy} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 380, textAlign: "center", fontFamily: SANS, color: NAVY }}>
        <div style={{ fontSize: 54, fontWeight: 700 }}>… and so on, through request 10</div>
        <div style={{ fontSize: 30, color: INK, marginTop: 18 }}>
          every request builds on earlier ones, and every request is judged with {data.check_counts[1]} checks: 3 functional, 1 integration, 1 backward
        </div>
      </div>
      <Caption frame={frame - 10}>Per-request pass rates of this app, from the released trace.</Caption>
    </AbsoluteFill>
  );
};

const Finale: React.FC = () => {
  const frame = useCurrentFrame();
  const total = FINALE;
  return (
    <AbsoluteFill>
      <Img src={manimFrame("sweep", Math.floor((frame * MANIM_FPS) / FPS), total)} style={{ width: 1920, height: 1080 }} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- the film
export const Demo: React.FC = () => {
  const frame = useCurrentFrame();
  useVideoConfig();
  let t = INTRO;
  const beats = BEATS.map((b, i) => {
    const start = t;
    t += beatLen(b);
    return { b, start, i };
  });
  const fastStart = t;
  const finaleStart = t + FAST;
  const inBeat = beats.find((x) => frame >= x.start && frame < x.start + beatLen(x.b));
  const litBefore = inBeat ? inBeat.i : frame >= fastStart ? 3 : 0;
  const tickOf = (x: (typeof beats)[number]) => x.start + beatLen(x.b) - x.b.tick;
  const lit = inBeat && frame >= tickOf(inBeat) ? inBeat.i + 1 : litBefore;

  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <Sequence from={0} durationInFrames={INTRO}>
        <IntroClip />
      </Sequence>
      {frame >= INTRO && frame < fastStart && <Header current={inBeat ? inBeat.i : 0} lit={lit} accuracy={data.accuracy} />}
      {beats.map(({ b, start, i }) => {
        const req = data.requests[i];
        let s = start;
        const seq = (len: number, el: React.ReactNode) => {
          const from = s;
          s += len;
          return (
            <Sequence key={`${i}-${from}`} from={from} durationInFrames={len}>
              {el}
            </Sequence>
          );
        };
        return (
          <React.Fragment key={i}>
            {seq(b.bubble, <Bubble req={req} idx={i} />)}
            {seq(b.agent, <Agent req={req} dur={b.agent} />)}
            {seq(b.app, <AppRender req={req} />)}
            {seq(b.judge, <Judge req={req} dur={b.judge} />)}
            {seq(b.tick, <Tick req={req} />)}
          </React.Fragment>
        );
      })}
      <Sequence from={fastStart} durationInFrames={FAST}>
        <FastForward />
      </Sequence>
      <Sequence from={finaleStart} durationInFrames={FINALE}>
        <Finale />
      </Sequence>
      <Sequence from={finaleStart + FINALE} durationInFrames={RESULTS_FRAMES}>
        <Results />
      </Sequence>
      {frame < finaleStart && <Footer />}
    </AbsoluteFill>
  );
};

const Tick: React.FC<{ req: (typeof data.requests)[number] }> = ({ req }) => {
  const frame = useCurrentFrame();
  const p = spring({ frame, fps: FPS, config: { damping: 12, stiffness: 140 } });
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 0, right: 0, top: 420, textAlign: "center", fontFamily: SANS, color: NAVY, transform: `scale(${0.8 + 0.2 * p})`, opacity: p }}>
        <div style={{ fontSize: 76, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{req.accuracy.toFixed(0)}%</div>
        <div style={{ fontSize: 28, color: INK }}>of request {req.id.slice(1)}'s checks passed · recorded on the timeline</div>
      </div>
    </AbsoluteFill>
  );
};

const IntroClip: React.FC = () => {
  const frame = useCurrentFrame();
  return <Img src={manimFrame("timeline", Math.floor((frame * MANIM_FPS) / FPS), INTRO)} style={{ width: 1920, height: 1080 }} />;
};

const Footer: React.FC = () => (
  <div style={{ position: "absolute", left: 80, bottom: 14, fontFamily: SANS, fontSize: 16, color: MUTED }}>
    EvoWeb · app {data.app} of {data.run} · every screenshot, tool call and judge step is from the released trace
  </div>
);
