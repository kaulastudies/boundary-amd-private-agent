# Architecture

The browser UI talks only to the local FastAPI backend. The backend will later
coordinate the modules under `agent/` and a concrete `LocalModelClient` backed
by an on-device AMD-compatible runtime.

Security boundaries:

1. Local inference is the only supported model path.
2. Permission checks precede sensitive tool execution.
3. Audit events record decisions and approved actions.
4. No final model or runtime integration is part of this scaffold.
