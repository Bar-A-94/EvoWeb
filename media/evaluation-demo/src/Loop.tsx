import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import data from "../public/data.json";
import { INK, KIND, LINE, MUTED, NAVY, NODE_EDGE, NODE_FILL, PAPER, SANS, VERDICT } from "./theme";
import { AgentIcon, JudgeIcon, UserAvatar } from "./Icons";

const FPS = 30;
export const LOOP_FRAMES = 15 * FPS;

/** A 15-second silent loop for the README: request, build, judge, score, three times, in one frame. */
export const Loop: React.FC = () => {
  const frame = useCurrentFrame();
  const per = LOOP_FRAMES / 3;
  const i = Math.min(2, Math.floor(frame / per));
  const local = frame - i * per;
  const req = data.requests[i];
  const phase = local / per; // 0..1
  const stage = phase < 0.22 ? 0 : phase < 0.5 ? 1 : phase < 0.85 ? 2 : 3;
  const stepIdx = Math.min(req.judge.steps.length - 1, Math.floor(((phase - 0.5) / 0.35) * req.judge.steps.length));
  const step = req.judge.steps[Math.max(0, stepIdx)];
  const fade = interpolate(local, [0, 8, per - 8, per], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: PAPER, fontFamily: SANS }}>
      <div style={{ position: "absolute", top: 22, left: 40, display: "flex", gap: 8, alignItems: "center" }}>
        {Array.from({ length: 10 }, (_, k) => {
          const on = k < i || (k === i && stage === 3);
          return (
            <div key={k} style={{ width: 92, height: 46, borderRadius: 9, border: `2px solid ${k <= i ? NODE_EDGE[k % 5] : LINE}`, background: k <= i ? NODE_FILL[k % 5] : "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: k <= i ? NAVY : MUTED, fontSize: 16, fontWeight: 700 }}>
              R{k + 1}
              <span style={{ fontSize: 12, fontWeight: 400, color: INK, opacity: on ? 1 : 0 }}>{data.accuracy[k].toFixed(0)}%</span>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", top: 100, left: 40, right: 40, bottom: 30, opacity: fade }}>
        {stage === 0 && (
          <div style={{ display: "flex", gap: 18, alignItems: "flex-start", marginTop: 90 }}>
            <UserAvatar size={64} />
            <div style={{ background: "#fff", border: `2px solid ${NAVY}`, borderRadius: 16, padding: "18px 24px", fontSize: 26, color: INK, lineHeight: 1.35, maxWidth: 1000 }}>
              <div style={{ fontSize: 14, color: MUTED, letterSpacing: 1, marginBottom: 6 }}>REQUEST {req.id.slice(1)} · {req.label.toUpperCase()}</div>
              {req.text.slice(0, Math.floor(local * 2.2))}
            </div>
          </div>
        )}
        {stage === 1 && (
          <div style={{ background: "#0f1b2d", color: "#d6e2f0", borderRadius: 14, padding: "18px 24px", fontFamily: "Menlo, monospace", fontSize: 19, lineHeight: 1.5, height: 520 }}>
            <div style={{ color: "#7f93ad", display: "flex", alignItems: "center", gap: 10 }}><AgentIcon size={24} color="#9fb3cc" /> coding agent (OpenHands · {data.model}) extends the app</div>
            {req.calls.slice(0, Math.min(req.calls.length, Math.floor((local - per * 0.22) / 3.5))).slice(-11).map((c, k) => (
              <div key={k} style={{ whiteSpace: "nowrap", overflow: "hidden" }}>
                <span style={{ color: c.kind === "edit" ? "#f2c879" : "#7fd1a8" }}>{c.kind === "edit" ? "✎ " : "▶ "}</span>
                {c.title}
              </div>
            ))}
          </div>
        )}
        {stage === 2 && (
          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ width: 760, flexShrink: 0, borderRadius: 12, overflow: "hidden", border: `1.5px solid ${LINE}`, background: "#0b1626" }}>
              <Img src={staticFile(step.shot)} style={{ width: 760, height: 371, display: "block" }} />
              <div style={{ color: "#d6e2f0", padding: "10px 16px", fontSize: 16, height: 110 }}>
                <span style={{ color: "#7f93ad", fontSize: 12, letterSpacing: 1, display: "flex", alignItems: "center", gap: 6 }}><JudgeIcon size={16} color="#9fb3cc" /> JUDGE THINKS</span>
                <div style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{step.thought}</div>
                <div style={{ color: "#7fd1a8", fontFamily: "Menlo, monospace", marginTop: 4 }}>{step.action}</div>
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, color: MUTED, letterSpacing: 1 }}>{req.checks.length} CHECKS</div>
              {req.checks.map((c, k) => {
                const kind = KIND[c.kind] ?? KIND.feature;
                const v = VERDICT[c.verdict] ?? VERDICT.no;
                const done = phase > 0.5 + 0.35 * ((k + 1) / req.checks.length);
                return (
                  <div key={k} style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, fontSize: 17 }}>
                    <div style={{ width: 8, height: 22, background: kind.color, borderRadius: 2 }} />
                    <div style={{ width: 100, color: kind.color, fontWeight: 600 }}>{kind.label}</div>
                    <div style={{ flex: 1, color: INK, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.task}</div>
                    <div style={{ width: 28, height: 28, borderRadius: 14, background: done ? v.color : "#eef2f7", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700 }}>{done ? v.glyph : ""}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {stage === 3 && (
          <div style={{ textAlign: "center", marginTop: 150, color: NAVY }}>
            <div style={{ fontSize: 96, fontWeight: 700 }}>{req.accuracy.toFixed(0)}%</div>
            <div style={{ fontSize: 24, color: INK }}>of request {req.id.slice(1)}'s checks passed</div>
          </div>
        )}
      </div>
      <div style={{ position: "absolute", left: 40, bottom: 10, fontSize: 13, color: MUTED }}>EvoWeb · one app, request after request · real trace of {data.run}</div>
    </AbsoluteFill>
  );
};
