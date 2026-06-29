# Launch and growth playbook

A practical plan to publicize the project, attract contributors, and rank highly when people
search for a Cognos to Power BI migration tool. No paid advertising required.

## Positioning

- One sentence: "Open-source, AI-assisted tool to migrate IBM Cognos reports to Microsoft Power BI."
- Primary keyword: **Cognos to Power BI migration**.
- Secondary keywords: convert Cognos reports to Power BI, IBM Cognos to Power BI tool, Cognos
  report converter, PBIP TMDL generator, Cognos modernization.

## Search ranking (SEO) checklist

Search engines rank repositories on relevance, authority, and freshness. Optimize all three.

### Repository configuration

- Name the repository `cognos-to-powerbi` (hyphenated, keyword-first).
- Set the GitHub **About** description to the one-sentence positioning above.
- Add topics: `cognos`, `power-bi`, `powerbi`, `migration`, `pbip`, `tmdl`, `pbir`,
  `business-intelligence`, `cognos-to-powerbi`, `report-conversion`.
- Set the repository website to your docs or landing page.
- Enable Discussions and Issues.

### On-page content

- The README H1 and first paragraph must contain the primary keyword naturally (already done).
- Keep a keyword footer in the README (already done).
- Use descriptive, keyword-bearing headings in `docs/`.
- Publish docs to GitHub Pages so each page is independently indexable.
- Add real, anonymized before/after examples; long-form, useful content ranks and earns links.

### Authority (backlinks)

- Submit to curated lists: `awesome-powerbi`, `awesome-business-intelligence`, and similar.
- Write a launch post on a blog you control and link to the repo with the primary keyword as the
  anchor text.
- Answer existing Stack Overflow and Reddit questions about Cognos-to-Power BI migration with a
  genuine, helpful answer that references the tool where appropriate.
- Add the project to the Microsoft Fabric / Power BI community galleries where allowed.

### Freshness

- Ship small, frequent releases and keep `CHANGELOG.md` current.
- Keep the coverage matrix and roadmap updated; movement signals an active project.

## Launch sequence

1. **Pre-launch.** Finish a clean end-to-end demo on a real anonymized report. Record a short
   screen capture. Write the launch post.
2. **GitHub.** Publish the repo, tag `v0.1.0`, enable Discussions, label `good first issue`s.
3. **Show HN / Reddit.** Post to Hacker News ("Show HN") and relevant subreddits
   (`r/PowerBI`, `r/BusinessIntelligence`, `r/dataengineering`). Lead with the problem and the
   demo, not the marketing.
4. **LinkedIn and dev communities.** Share the launch post; ask for feedback, not stars.
5. **Microsoft and BI communities.** Post in the Power BI Community and Microsoft Fabric forums.
6. **Follow up.** Respond to every issue and comment within a day during launch week. Early
   responsiveness converts visitors into contributors.

## Community building

- Maintain `good first issue` and `help wanted` labels with small, well-scoped tasks.
- Add a `CONTRIBUTING.md` quick-start (done) and a clear architecture doc (done).
- Triage issues weekly and thank contributors publicly.
- Publish a short monthly update summarizing progress and shoutouts.

## Measuring success

- Stars and forks are vanity; track contributors, merged external PRs, and closed real-world
  migration issues.
- Track search ranking for the primary keyword monthly.
- Track successful migrations reported by users.

## SaaS conversion (later)

When the engine is robust, wrap it with the FastAPI backend, add upload/review/download and auth,
and offer a hosted tier for teams that cannot run the CLI. Keep the engine open-source; monetize
hosting, batch scale, and support.
