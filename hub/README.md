# aboutali.github.io — hub page

Personal landing page that lists all GitHub Pages projects under [github.com/aboutali](https://github.com/aboutali). Once published, it serves as the root URL `https://aboutali.github.io/` and links out to each project page (which live at `https://aboutali.github.io/<repo-name>/`).

This directory contains a single self-contained `index.html` (inline CSS, light/dark mode, no build step). It's scaffolded here because the Claude Code session that produced it is scoped to `aboutali/bxl_eda_worker`; the file is meant to be moved into a dedicated `aboutali/aboutali.github.io` repo to actually go live.

## Publish it (one-time setup)

```bash
# 1. Create the repo on GitHub (must be named exactly aboutali.github.io)
gh repo create aboutali/aboutali.github.io --public --description "Personal hub" --confirm

# 2. Bootstrap from this scaffold
mkdir ~/aboutali.github.io && cd ~/aboutali.github.io
git init -b main
cp /path/to/bxl_eda_worker/hub/index.html .
git add index.html
git commit -m "Initial hub page"
git remote add origin git@github.com:aboutali/aboutali.github.io.git
git push -u origin main
```

GitHub Pages auto-publishes any repo named `<user>.github.io` from the default branch root. Visit `https://aboutali.github.io/` — propagation takes a minute or two on first publish.

## Add a new project

Open `index.html` and add an `<li>` to `ul.project-list`:

```html
<li>
  <p class="project-title"><a href="https://aboutali.github.io/<repo-name>/"><repo-name></a></p>
  <p class="project-desc">One-sentence description.</p>
  <div class="project-links">
    <span class="tag">Language</span>
    <a href="https://aboutali.github.io/<repo-name>/">site →</a>
    <a href="https://github.com/aboutali/<repo-name>">source →</a>
  </div>
</li>
```

Commit and push to `main`; the hub redeploys in ~1 minute.

## Conventions

- **Order**: most recent / most active project first.
- **Tag**: primary language or stack (`Python`, `TypeScript`, `Rust`, …) — keep it to one.
- **Description**: one sentence, present tense, no marketing.
- **Links**: always pair `site →` (the rendered Pages URL) with `source →` (the repo). Drop `site →` for repos without a Pages site.
