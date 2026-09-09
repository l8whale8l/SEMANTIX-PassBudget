# SEMANTIX PassBudget

[한국어](README.md) | [English](README_EN.md)

> An open-source downlink planning tool that helps satellite teams decide **how much data they can send and what should go first** during limited contact time.

![SEMANTIX PassBudget interface](assets/passbudget-ui.png)

## Overview

| Input | Calculation | Output |
|---|---|---|
| Orbit, ground stations, and link assumptions | Contact windows, pass capacity, and delivery order | Data budget, delivered data, remaining data, and decision evidence |

Save different assumptions as scenarios, compare them, and treat every result as a reviewable estimate—not a guarantee of reception.

## What can it do?

| Feature | What you get |
|---|---|
| Configure an orbit and ground stations | AOS/LOS, contact duration, and maximum elevation |
| Enter communication assumptions | Transfer capacity per pass and analysis period |
| Build a data cart | Fully delivered, partially delivered, and undelivered outputs by priority |
| Compare scenarios | The effect of changing stations, data rates, or scheduling policy |

## Who is it for?

| Team | How it helps |
|---|---|
| Satellite and mission design | Turn incomplete early specifications into comparable assumptions |
| Onboard AI and payload | Connect model outputs to a realistic transfer budget |
| Ground station and communication | See how station count, data rate, and contact time affect delivery |

## Getting started

### 1. Prepare the project

You need Python 3.12 and Node.js. SQLite is the default storage, so a separate database server is not required.

```bash
git clone https://github.com/l8whale8l/SEMANTIX-PassBudget.git
cd SEMANTIX-PassBudget
python -m venv .venv
```

```bash
# Windows
.venv\Scripts\python -m pip install -e ".[dev]"

# Linux / macOS
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### 2. Check the calculation engine

```bash
passbudget verify-golden
passbudget run PB-GOLDEN-ORB-01 --output result.json
```

The CLI and web API use the same calculation path. The first command checks that the frozen reference scenarios still produce the expected results. The second saves one result as JSON.

### 3. Start the web interface

Run the API in terminal 1:

```bash
uvicorn semantix_passbudget.interfaces.api.app:app --host 127.0.0.1 --port 8000
```

Run the frontend in terminal 2:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173` in your browser.

### 4. Run a scenario

| Step | Action |
|---:|---|
| 1 | Load the public synthetic preset or create a scenario. |
| 2 | Enter the orbit, station coordinates, minimum elevation, and analysis period. |
| 3 | Enter the data rate, efficiency, and safety margin. |
| 4 | Add each output's size, priority, deadline, and segmentation rule. |
| 5 | Run the scenario and inspect pass capacity, delivered data, and remaining data. |
| 6 | Change an assumption, run again, and compare the results. |

### 5. Read the results

| Label | Meaning |
|---|---|
| Transfer budget | Total usable capacity in the selected contact schedule |
| Candidate capacity | Theoretical total before resolving contact conflicts |
| Allocated | Data scheduled for transfer |
| Remaining | Data that cannot be sent within the analysis period |
| `EXACT` | A globally optimal result under the defined assumptions |
| `APPROXIMATE` | A deterministic feasible result without a global-optimum guarantee |

## Engine verification

| Method | Result |
|---|---|
| Independent comparison with NASA GMAT R2026a using frozen inputs | 58 matching passes and 0 tolerance violations |
| Predefined limits for AOS, LOS, duration, and maximum elevation | Worst error: AOS 0.017 s, LOS 0.014 s, duration 0.026 s, elevation 0.0051° |

This verifies agreement on defined test cases. It does not certify the real performance of a specific satellite or radio link.

## Team

**SEMANTIX** is a Korean student engineering team formed by undergraduates from Chonnam National University and Kookmin University.
We build small, verifiable tools that help mission teams compare limited communication resources with clear evidence.

## Public repository policy

Do not commit private mission names, specifications, coordinates, credentials, or server information.
Examples must use public or synthetic data, and assumptions must remain clearly labeled in every result.

## License

Released under the [MIT License](LICENSE).
