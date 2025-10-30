# humidor base codebase

Builds the codebase that every `humidor` server operation forks from.
`humidor serve` builds it on first use (`humidor serve --rebuild-base` to rebuild).
Pin library versions here; bump them deliberately. @unison/json must be the
version @unison/routes depends on, or their Json types will not match.

```ucm
scratch/main> project.create-empty humidor
humidor/main> lib.install @unison/base/releases/7.20.0
humidor/main> lib.install @unison/cloud/releases/27.3.1
humidor/main> lib.install @unison/routes/releases/7.0.2
humidor/main> lib.install @unison/json/releases/1.3.5
```
