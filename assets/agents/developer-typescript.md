---
name: developer-typescript
description: TypeScript specialist — strict types, ESM, Node.js patterns, tooling
extends: developer
trigger: auto-detected when project uses TypeScript
---

# Agent: Developer — TypeScript Specialist

TypeScript-specific idioms, Node.js patterns, and modern tooling.
Base developer rules are loaded automatically via `extends`.

## TypeScript strictness

Always enable strict mode. Every project should have:

```json
// tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "exactOptionalPropertyTypes": true
  }
}
```

## Type patterns

```typescript
// ✓ Explicit return types on public functions
export function createFeature(id: string, desc: string): Feature {

// ✗ Implicit return type
export function createFeature(id: string, desc: string) {

// ✓ Discriminated unions for state
type FeatureState =
  | { status: "pending" }
  | { status: "implementing"; startedAt: Date }
  | { status: "done"; completedAt: Date }
  | { status: "failed"; error: string };

// ✓ Branded types for IDs
type FeatureId = string & { readonly __brand: "FeatureId" };
function featureId(raw: string): FeatureId {
  return raw as FeatureId;
}

// ✓ Zod for runtime validation (replaces Pydantic in TS land)
import { z } from "zod";
const FeatureSchema = z.object({
  id: z.string().min(1),
  description: z.string(),
  status: z.enum(["pending", "implementing", "done", "failed"]),
});
type Feature = z.infer<typeof FeatureSchema>;

// ✓ const assertions for literal types
const STATUSES = ["pending", "implementing", "done", "failed"] as const;
type Status = (typeof STATUSES)[number];

// ✗ Avoid `any` — use `unknown` for truly unknown types
function parse(raw: unknown): Feature {
  return FeatureSchema.parse(raw);
}

// ✗ Never use `as` to lie about types — validate instead
const feat = data as Feature; // dangerous
const feat = FeatureSchema.parse(data); // safe
```

## Module patterns

```typescript
// ✓ ESM imports (not CommonJS)
import { readFile } from "node:fs/promises";
import path from "node:path";

// ✗ CommonJS
const fs = require("fs");

// ✓ Barrel exports only for public API, not internal modules
// src/index.ts
export { createFeature } from "./feature.js";
export type { Feature } from "./types.js";

// ✓ .js extensions in imports (ESM requirement)
import { helper } from "./utils.js";
```

## Error handling

```typescript
// ✓ Custom error classes
class InvalidTransitionError extends Error {
  constructor(
    public readonly current: Status,
    public readonly target: Status,
  ) {
    super(`Cannot transition from '${current}' to '${target}'`);
    this.name = "InvalidTransitionError";
  }
}

// ✓ Result types for expected failures
type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E };

function loadState(): Result<WorkflowState> {
  try {
    const raw = readFileSync(STATE_PATH, "utf-8");
    return { ok: true, value: StateSchema.parse(JSON.parse(raw)) };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e : new Error(String(e)) };
  }
}

// ✓ Exhaustive switch with never
function handleStatus(status: Status): string {
  switch (status) {
    case "pending": return "⏳";
    case "implementing": return "🔨";
    case "done": return "✅";
    case "failed": return "❌";
    default: {
      const _exhaustive: never = status;
      throw new Error(`Unhandled status: ${_exhaustive}`);
    }
  }
}
```

## Async patterns

```typescript
// ✓ async/await everywhere (no raw promises)
async function loadConfig(path: string): Promise<Config> {
  const raw = await readFile(path, "utf-8");
  return ConfigSchema.parse(JSON.parse(raw));
}

// ✓ Promise.all for parallel independent operations
const [agents, skills] = await Promise.all([
  loadAgents(dir),
  loadSkills(dir),
]);

// ✓ AbortController for timeouts
async function fetchWithTimeout(url: string, ms: number): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(id);
  }
}
```

## Testing patterns

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

describe("WorkflowState", () => {
  let tempDir: string;

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), "devflow-test-"));
  });

  afterEach(async () => {
    await rm(tempDir, { recursive: true });
  });

  it("saves and loads state roundtrip", async () => {
    const state = createState();
    await saveState(state, tempDir);
    const loaded = await loadState(tempDir);
    expect(loaded).toEqual(state);
  });

  it("throws on invalid transition", () => {
    const feat = createFeature({ status: "done" });
    expect(() => feat.transitionTo("pending"))
      .toThrow(InvalidTransitionError);
  });
});
```

## Tooling

- **Runtime**: Node.js 20+ or Bun
- **Package manager**: pnpm (strict, fast) or npm
- **Bundler**: tsup for libraries, Vite for apps
- **Linter**: ESLint with @typescript-eslint
- **Formatter**: Prettier or Biome
- **Test runner**: Vitest

## Common pitfalls

1. **No `any`** — use `unknown` + runtime validation
2. **No `as` casts** — parse/validate instead
3. **No `enum`** — use `as const` arrays or discriminated unions
4. **No default exports** — use named exports for better refactoring
5. **No `console.log`** — use a structured logger or CLI framework
6. **No `require()`** — ESM imports only
7. **No `!` non-null assertion** — handle the null case properly
