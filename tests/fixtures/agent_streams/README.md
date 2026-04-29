# Captured agent stream fixtures

This directory is reserved for real `claude -p --output-format stream-json` captures
used as anchors for parser tests in `tests/test_agent_runner_parse.py`.

## Why

Synthetic NDJSON in the test file matches the documented event shape today, but a
real capture catches drift if Claude Code changes its emission format.

## How to capture

Run a developer task that fans out via the `Task` tool to implementer + reviewer
subagents, redirecting stdout:

```bash
claude -p "<your prompt>" \
  --verbose \
  --model claude-sonnet-4-6 \
  --output-format stream-json \
  --allowedTools bash,read,write \
  > tests/fixtures/agent_streams/developer_with_subagents.ndjson
```

Add a top-of-file comment line in the NDJSON noting the capture date and the
output of `claude --version`. The parser test file may then load and parse the
fixture as an additional assertion.

## Status

Not currently populated. The nine scenarios in `test_agent_runner_parse.py`
use synthetic NDJSON sufficient to exercise every documented branch of
`_parse_json_output`.
