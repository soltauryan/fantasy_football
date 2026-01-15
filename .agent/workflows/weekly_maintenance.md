---
description: Weekly Fantasy Football Maintenance Workflow
---

# Weekly Fantasy Football Maintenance

Follow this workflow every Tuesday/Wednesday to prepare for waivers and set your lineup.

## 1. Refresh Data
Download the latest stats, scores, and free agent info from ESPN.

```bash
python etl/ingest_espn.py
```

## 2. Run Weekly Optimizer
Analyze your team, identify start/sit candidates, and find waiver targets.

```bash
# Replace 'Your Team Name' with your actual team name (e.g., "Basement Boyz n Girlz")
python analysis/weekly_optimizer.py --team "Your Team Name"
```

## 3. Review Implementation
- **Roster Optimization**: Check if any bench players are projected to outscore your starters.
- **Waiver Wire**: Look for free agents with high projected points to replace your bottom-performing players.
