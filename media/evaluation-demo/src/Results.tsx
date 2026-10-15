import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import data from "../public/data.json";
import { INK, LINE, MUTED, NAVY, PAPER, SANS } from "./theme";

const FPS = 30;
export const RESULTS_FRAMES = 6 * FPS;
const CLOSED = "#2f5f8f";
const OPEN = "#3f8f5f";

/** The paper's Table 2 as a bar chart of Grade, with Survival and cost beside each bar. */
export const Results: React.FC = () => {
  const f = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const tall = width / height < 1.3;
  const rows = data.table2;
  const top = tall ? 235 : 150;
  const left = tall ? 40 : 160;
  const w = width - 2 * left;
  const rowH = Math.min(tall ? 64 : 54, (height - top - 140) / rows.length);
  const labelW = tall ? 210 : 260;
  const numsW = tall ? 190 : 300;
  const barMax = w - labelW - numsW - 24;
  const fs = tall ? 20 : 23;
  const titleIn = spring({ frame: f, fps: FPS, config: { damping: 200 } });
  return (
    <AbsoluteFill style={{ background: PAPER, fontFamily: SANS, color: NAVY }}>
      <div style={{ position: "absolute", left, right: left, top: tall ? 44 : 40, opacity: titleIn }}>
        <div style={{ fontSize: tall ? 40 : 50, fontWeight: 700, lineHeight: 1.1 }}>Main results: no model keeps an app working for all ten requests</div>
        <div style={{ fontSize: tall ? 20 : 24, color: MUTED, marginTop: 8, display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap" }}>
          <span>Grade (area under quality over tolerance, 0 to 1) · Survival (requests before failure, of 10) · mean of 3 runs over 32 apps</span>
        </div>
      </div>
      <div style={{ position: "absolute", left, top, width: w }}>
        <div style={{ display: "flex", fontSize: fs - 4, color: MUTED, letterSpacing: 1, marginBottom: 6 }}>
          <div style={{ width: labelW }}>MODEL</div>
          <div style={{ width: barMax }}>GRADE</div>
          <div style={{ width: numsW, display: "flex", justifyContent: "space-between", paddingLeft: 16 }}>
            <span>SURVIVAL</span>
            <span>$ / APP</span>
          </div>
        </div>
        {rows.map((r, i) => {
          const p = spring({ frame: f - 10 - i * 3, fps: FPS, config: { damping: 200, stiffness: 110 } });
          const color = r.open ? OPEN : CLOSED;
          return (
            <div key={r.model} style={{ display: "flex", alignItems: "center", height: rowH, opacity: interpolate(p, [0, 0.2], [0, 1], { extrapolateRight: "clamp" }) }}>
              <div style={{ width: labelW, fontSize: fs, fontWeight: i === 0 ? 700 : 500, color: INK, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingRight: 10 }}>{r.model}</div>
              <div style={{ width: barMax, position: "relative", height: rowH * 0.62 }}>
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: barMax, background: "#eef2f7", borderRadius: 6 }} />
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: barMax * r.grade * p, background: color, borderRadius: 6 }} />
                <div style={{ position: "absolute", left: Math.min(barMax * r.grade * p + 10, barMax - 70), top: 0, bottom: 0, display: "flex", alignItems: "center", fontSize: fs, fontWeight: 700, color: NAVY, fontVariantNumeric: "tabular-nums" }}>
                  {r.grade.toFixed(3)}
                </div>
              </div>
              <div style={{ width: numsW, display: "flex", justifyContent: "space-between", paddingLeft: 16, fontSize: fs, color: INK, fontVariantNumeric: "tabular-nums" }}>
                <span>{r.survival.toFixed(2)}</span>
                <span style={{ color: MUTED }}>{r.usd.toFixed(2)}</span>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left, bottom: tall ? 40 : 36, display: "flex", gap: 26, fontSize: fs - 2, color: INK, alignItems: "center", opacity: interpolate(f, [40, 55], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 16, height: 16, borderRadius: 4, background: CLOSED }} /> closed API model</span>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 16, height: 16, borderRadius: 4, background: OPEN }} /> open weights</span>
        <span style={{ color: MUTED, borderLeft: `1px solid ${LINE}`, paddingLeft: 20 }}>Table 2 of the paper</span>
      </div>
    </AbsoluteFill>
  );
};
