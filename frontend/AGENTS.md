# AGENTS.md — CADMorph

CADMorph is a Python/FastAPI backend + React/Vite frontend for CAD drawing
change detection. Backend and API contract are COMPLETE and gated by 100+
tests — they are NOT to be modified by any frontend task unless explicitly
instructed otherwise in a specific prompt.

## Hard rules for ANY frontend task
- Only touch files under `frontend/`. Never edit `backend/`, `.specify/`,
  `specs/`, or any `.py` file.
- Never change an API route path, request field name, or response field name.
  Treat `backend/src/cadmorph/api/routes.py` and
  `specs/001-pdf-change-detection/contracts/api.md` as read-only ground truth
  to consume, not to negotiate with.
- The frontend must build with zero TypeScript errors (`tsc -b`) before you
  consider a task done.
- Never introduce localStorage/sessionStorage or any new backend dependency.