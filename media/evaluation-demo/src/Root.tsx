import React from "react";
import { Composition } from "remotion";
import { Demo, DEMO_FRAMES, FPS } from "./Demo";
import { Loop, LOOP_FRAMES } from "./Loop";
import { Teaser, teaserFrames } from "./Teaser";

export const Root: React.FC = () => (
  <>
    <Composition id="EvoWebDemo" component={Demo} durationInFrames={DEMO_FRAMES} fps={FPS} width={1920} height={1080} />
    <Composition id="EvoWebTeaser" component={Teaser} durationInFrames={teaserFrames(false, false)} fps={FPS} width={1920} height={1080} defaultProps={{ results: false, hook: false }} />
    <Composition id="EvoWebTeaserSquare" component={Teaser} durationInFrames={teaserFrames(true)} fps={FPS} width={1080} height={1080} defaultProps={{ results: true }} />
    <Composition id="EvoWebLoop" component={Loop} durationInFrames={LOOP_FRAMES} fps={FPS} width={1280} height={720} />
  </>
);
