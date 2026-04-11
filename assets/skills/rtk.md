# Skill: RTK (Reduce Token Krunch)

Rules for minimizing token usage in agent operations.

## Principles

1. **Targeted reads** — Read specific line ranges, not entire files.
   Use offset/limit when you know which section you need.

2. **Filter noise** — When running commands, pipe through filters to reduce
   output. Use `--quiet`, `-q`, `--short` flags when available.

3. **Structured output** — Prefer JSON or machine-readable output over
   verbose human-readable output when processing results.

4. **Skip known-good** — Don't re-read files you just wrote. Don't re-run
   tests that haven't been affected by your changes.

5. **Compress feedback** — In reports, lead with the verdict, then details
   only for failures.

## Token-heavy operations to avoid

- Running `git diff` on the entire repo when you only changed one file
- Reading test output verbosely when you just need pass/fail
- Loading workflow YAML files you're not going to use
- Re-reading models.py when you only need one class
