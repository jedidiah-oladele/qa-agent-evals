# Sandbox image for agent episodes and grading.
#   docker build -t qa-agent-evals-sandbox:1 -f harness/docker/Dockerfile .
# Contains Python 3.12 + pytest (shopcore), Node 22 + ledgerkit's locked
# dev dependencies (vitest, typescript) at /opt/ledgerkit/node_modules.
# No task files, hidden tests or repository code are baked in: each container
# only ever sees the one workspace directory mounted at /work.
#
# Optional: --build-arg NATIVE=1 also installs the Claude Code and Codex CLIs
# for native-harness runs (those containers get network access to reach the
# vendor API; shared-loop and grading containers never do).
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
ARG NATIVE=0
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update && apt-get install -y --no-install-recommends git ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "pytest==9.1.1"
COPY target/ledgerkit/package.json target/ledgerkit/package-lock.json /opt/ledgerkit/
RUN cd /opt/ledgerkit && npm ci --no-audit --no-fund && chmod -R a-w /opt/ledgerkit
RUN if [ "$NATIVE" = "1" ]; then npm install -g @anthropic-ai/claude-code @openai/codex; fi
ENV PYTHONDONTWRITEBYTECODE=1 CI=1 TZ=UTC
WORKDIR /work
CMD ["sleep", "infinity"]
