# corn/ — kniox scheduled jobs

Two complementary overseers, on different brains and different budgets:

| Job | Brain | Budget | Cadence | Writes |
|---|---|---|---|---|
| **custodian** | local LLM (idle GPU) | free compute | nightly | `custodian/reports/` (read-only survey) |
| **scout** | Claude (paid quota) | paid tokens | a few times/day | **GitHub issues** (deduped, self-capped) |

The custodian surveys the framework with the local model and writes a "state of the
framework" report. The scout reads that report (plus repo state) and turns the best
opportunities into GitHub issues — so the **paid Claude tokens don't go to waste**. The scout
is **issues-only**: it never edits code, commits, or opens PRs; it dedups against open issues
and stops itself once 8 `scout`-labeled issues are open.

Install both into your crontab (idempotent; preserves your other cron entries):

    ~/kniox/corn/install-cron.sh          # install / update
    ~/kniox/corn/install-cron.sh --remove # remove the kniox block

## Jobs

- `scout.sh` + `scout.prompt.md` — Claude → GitHub issues, a few times/day.
- `custodian.sh` — nightly one-shot custodian run (cron).
- `custodian.service` — always-on custodian service (systemd **user** unit). Shipped, **not**
  auto-enabled. To enable:

      mkdir -p ~/.config/systemd/user
      cp ~/kniox/corn/custodian.service ~/.config/systemd/user/
      systemctl --user daemon-reload
      systemctl --user enable --now custodian

  It runs lowest-priority, only when the GPU is idle, and yields to real jobs.
