# The evaluation demo

`media/evaluation-demo.mp4` (74 s, 1080p) and `media/evaluation-demo.gif` (15 s loop, 640 px)
show part (B) of Figure 1 on one real app: app 000001 of `opus-4.8-run1`, requests 1 to 3, with the
agent's own tool calls, the app after each request, the judge's steps and verdicts, the per-request
pass rates of all 10 requests, and the app's Grade and Survival. Every screenshot, tool call, judge
thought and number is from `examples_artifacts/examples.zip` and `evoweb.metrics`; nothing is staged.

Two renderers: **Manim** draws the academic pieces (the request timeline, the tolerance sweep with its
areas) on a transparent background; **Remotion** composes the film (request bubbles, terminal, browser
frames, judge panel, captions) and embeds the Manim frames.

```bash
cd media/evaluation-demo
npm install                                        # remotion, react
pip install manim                                  # needs pkg-config + pango (brew install pkg-config pango)
(cd manim && manim -qh -t --fps 30 scenes.py Timeline Sweep)
mkdir -p public/manim/timeline public/manim/sweep
ffmpeg -i manim/media/videos/scenes/1080p30/Timeline.mov -vf format=rgba public/manim/timeline/%04d.png
ffmpeg -i manim/media/videos/scenes/1080p30/Sweep.mov    -vf format=rgba public/manim/sweep/%04d.png
python3 -c "import json,os;json.dump({k:len(os.listdir(f'public/manim/{k}')) for k in ('timeline','sweep')},open('public/manim/meta.json','w'))"
npx remotion render src/index.ts EvoWebDemo ../evaluation-demo.mp4 --codec=h264 --crf=20
npx remotion render src/index.ts EvoWebLoop ../evaluation-demo.gif --codec=gif --scale=0.5 --every-nth-frame=2
npx remotion render src/index.ts EvoWebTeaser       ../evaluation-teaser.mp4       # 16:9 for the blog, no results table
npx remotion render src/index.ts EvoWebTeaserSquare ../evaluation-teaser-1x1.mp4   # 1:1 for LinkedIn and X, with Table 2
```

`public/data.json` holds the material the film is cut from (requests, checks and verdicts, the agent's
tool calls per request, the judge's steps with their screenshots, the pass rates and the scores); it was
extracted from the example archive and the scoring code. `npx remotion studio src/index.ts` opens the
composition for editing.
