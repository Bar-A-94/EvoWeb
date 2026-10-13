# EvoWeb trace-generation harness: one container runs one app ladder (build + 9 follow-ups),
# agent (OpenHands by default) + WebVoyager judge.
#
# Build (context = the package root, the parent of harness/ and data/):
#   docker build -f harness/Dockerfile -t evoweb-harness:latest .
#
# Run one ladder:
#   docker run --rm \
#     -e SAMPLE_INDEX=1 -e API_KEY=sk-ant-... -e EVAL_API_KEY=sk-ant-... \
#     -v $(pwd)/runs/my-run:/output \
#     evoweb-harness:latest
#
# Run N ladders in parallel: harness/run_local.sh (see harness/README.md).

FROM ubuntu:22.04

# 1. System setup (Chrome + chromedriver, Python 3, Node 22, pm2, uv, awscli — the
#    latter only used when S3_BUCKET is set)
COPY harness/setup_instance.sh /opt/setup_instance.sh
RUN bash /opt/setup_instance.sh && rm /opt/setup_instance.sh

# Optional session-recording stack for --record-video / WEBGEN_RECORD_VIDEO=1
# (Xvfb virtual display + ffmpeg capture). Off by default; recording.py skips if absent.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 2. The harness and the dataset. data/ carries evoweb_benchmark.jsonl (the 32-app benchmark);
#    make_tasksets.py writes the smoke sets into /app/tests/smoke_sets/.
COPY harness/ /app/harness/
COPY data/    /app/data/
RUN python3 /app/harness/make_tasksets.py && test -f /app/data/evoweb_benchmark.jsonl

# Fail the BUILD if the worker's local imports do not resolve (a missing module used to
# surface only as a fleet of containers dying on ImportError seconds after start).
RUN cd /app/harness && python3 -c "import scoring, checkpoint, generators.backend, webvoyager.recording" \
    && python3 -m py_compile run_single_sample.py scoring.py checkpoint.py make_tasksets.py \
    && python3 -c "import compileall, sys; sys.exit(0 if compileall.compile_dir('/app/harness', quiet=1) else 1)" \
    && echo "harness local imports OK"
RUN chmod +x /app/harness/run_sample.sh /app/harness/run_single_sample.py

# 3. Chrome path for the WebVoyager judge (webvoyager/run.py reads ../.chrome_path, else CHROME_BIN)
RUN echo "/usr/bin/google-chrome" > /app/harness/.chrome_path

# 4. Environment
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver
ENV OUTPUT_DIR=/output
ENV PYTHONUNBUFFERED=1
# No S3 in the open-source package unless the user opts in.
ENV S3_BUCKET=none

WORKDIR /app/harness
ENTRYPOINT ["bash", "/app/harness/run_sample.sh"]
