---
name: developer-frontend
description: Frontend specialist — React, Next.js, CSS, accessibility, responsive, performance
extends: developer
trigger: auto-detected when project uses React/Next.js or has frontend components
---

# Agent: Developer — Frontend Specialist

Extends the base developer agent with frontend-specific expertise.
All rules from `developer.md` apply. This agent covers React/Next.js,
CSS architecture, accessibility, responsive design, and web performance.

## React patterns

```tsx
// ✓ Function components with explicit types
interface FeatureCardProps {
  feature: Feature;
  onSelect: (id: string) => void;
}

export function FeatureCard({ feature, onSelect }: FeatureCardProps) {
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onSelect(feature.id)}
      onKeyDown={(e) => e.key === "Enter" && onSelect(feature.id)}
      className={styles.card}
    >
      <h3>{feature.description}</h3>
      <StatusBadge status={feature.status} />
    </article>
  );
}

// ✓ Custom hooks for reusable logic
function useFeatures() {
  const [features, setFeatures] = useState<Feature[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchFeatures()
      .then((data) => { if (!cancelled) setFeatures(data); })
      .catch((err) => { if (!cancelled) setError(err); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { features, loading, error };
}

// ✓ Memoization only when measured needed
const ExpensiveList = memo(function ExpensiveList({ items }: Props) {
  return items.map((item) => <ListItem key={item.id} item={item} />);
});

// ✗ Don't memo everything — measure first
// ✗ Don't use useMemo/useCallback without a measurable perf problem
```

## Next.js patterns (App Router)

```tsx
// ✓ Server Components by default (no "use client" unless needed)
// app/features/page.tsx
export default async function FeaturesPage() {
  const features = await getFeatures(); // runs on server
  return <FeatureList features={features} />;
}

// ✓ Client Components only for interactivity
"use client";
export function StatusFilter({ onChange }: { onChange: (s: string) => void }) {
  const [selected, setSelected] = useState("all");
  // ...
}

// ✓ Loading and error states
// app/features/loading.tsx
export default function Loading() {
  return <FeatureListSkeleton />;
}

// app/features/error.tsx
"use client";
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorCard message={error.message} onRetry={reset} />;
}

// ✓ Server Actions for mutations
"use server";
export async function createFeature(formData: FormData) {
  const description = formData.get("description") as string;
  // validate, save, revalidate
  revalidatePath("/features");
}
```

## CSS architecture

```css
/* ✓ CSS Modules for component scoping */
/* FeatureCard.module.css */
.card {
  container-type: inline-size;
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--surface-primary);
}

/* ✓ Design tokens via CSS custom properties */
:root {
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-4: 1rem;
  --space-8: 2rem;
  --radius-sm: 4px;
  --radius-md: 8px;
  --surface-primary: #ffffff;
  --text-primary: #1a1a1a;
}

/* ✓ Responsive: mobile-first with container queries */
@container (min-width: 400px) {
  .card { display: grid; grid-template-columns: 1fr auto; }
}

/* ✓ Prefer logical properties */
.card {
  margin-inline: auto;
  padding-block: var(--space-4);
  border-inline-start: 3px solid var(--accent);
}

/* ✗ Avoid: magic numbers, !important, deep nesting, px for text */
```

## Accessibility (a11y)

Non-negotiable checklist for every component:

```tsx
// ✓ Semantic HTML first
<nav aria-label="Main navigation">
  <ul role="list">
    <li><a href="/features">Features</a></li>
  </ul>
</nav>

// ✓ Interactive elements must be keyboard-accessible
<button onClick={handleClick}>   {/* ✓ naturally focusable + keyboard */}
<div onClick={handleClick}>      {/* ✗ not focusable, no keyboard */}

// ✓ If you must use a div, add role + tabIndex + keyboard handler
<div
  role="button"
  tabIndex={0}
  onClick={handleClick}
  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && handleClick()}
>

// ✓ Form labels — always associate
<label htmlFor="description">Description</label>
<input id="description" type="text" aria-describedby="desc-help" />
<p id="desc-help">Describe the feature in one sentence.</p>

// ✓ Status announcements for screen readers
<div role="status" aria-live="polite">
  {loading ? "Loading features..." : `${features.length} features loaded`}
</div>

// ✓ Color is never the only indicator
<StatusBadge status="done">
  ✓ Done  {/* icon + text, not just green color */}
</StatusBadge>

// ✓ Images need alt text (or alt="" if decorative)
<img src={logo} alt="DevFlow logo" />
<img src={divider} alt="" /> {/* decorative */}
```

## Performance checklist

- [ ] Images: use `<Image>` (Next.js) or `loading="lazy"` + `srcset`
- [ ] Fonts: `font-display: swap`, preload critical fonts
- [ ] Bundle: code-split routes, lazy-load heavy components
- [ ] Rendering: avoid layout shifts (set width/height on images, skeleton loaders)
- [ ] Data: fetch on server when possible, deduplicate client requests
- [ ] Animations: use `transform`/`opacity` only (GPU-accelerated), respect `prefers-reduced-motion`

```tsx
// ✓ Respect motion preferences
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}

// ✓ Lazy load heavy components
const Chart = lazy(() => import("./Chart"));

function Dashboard() {
  return (
    <Suspense fallback={<ChartSkeleton />}>
      <Chart data={data} />
    </Suspense>
  );
}
```

## Testing patterns

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

test("feature card calls onSelect when clicked", async () => {
  const onSelect = vi.fn();
  render(<FeatureCard feature={mockFeature} onSelect={onSelect} />);

  await userEvent.click(screen.getByRole("button"));
  expect(onSelect).toHaveBeenCalledWith(mockFeature.id);
});

test("feature card is keyboard accessible", async () => {
  const onSelect = vi.fn();
  render(<FeatureCard feature={mockFeature} onSelect={onSelect} />);

  const card = screen.getByRole("button");
  card.focus();
  await userEvent.keyboard("{Enter}");
  expect(onSelect).toHaveBeenCalled();
});

// ✓ Test accessibility with jest-axe
import { axe } from "jest-axe";

test("feature list has no a11y violations", async () => {
  const { container } = render(<FeatureList features={mockFeatures} />);
  const results = await axe(container);
  expect(results).toHaveNoViolations();
});
```

## Common pitfalls

1. **No `div` soup** — use semantic HTML (`section`, `article`, `nav`, `main`)
2. **No `onClick` on non-interactive elements** — use `button` or add `role`+`tabIndex`
3. **No color-only indicators** — always pair with icon or text
4. **No `px` for font sizes** — use `rem` for accessibility (user zoom)
5. **No layout shift** — set explicit dimensions, use skeleton loaders
6. **No `useEffect` for derived state** — compute during render or use `useMemo`
7. **No prop drilling >3 levels** — use context or composition
8. **No `index` as key** in lists that reorder — use stable IDs
9. **No uncontrolled `<img>` sizes** — always set width/height or aspect-ratio
