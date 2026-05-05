# 🐝 Swarm AI — Multi-Agent Consensus

Ask one hard question. **Five AI agents** with different personas analyze it independently and **in parallel**. A sixth **synthesizer** agent reads all five viewpoints and writes a consensus answer with a calibrated **agreement score**.

The result: a more reliable answer than any single LLM call, with the disagreements made visible instead of averaged away.

## Why multi-agent?

A single LLM gives you one perspective and can hallucinate confidently. The "Mixture of Agents" pattern (Together AI 2024) showed that **a swarm of agents with different vantage points consistently outperforms any single agent** on hard reasoning tasks. This repo is a clean, working CLI implementation of that pattern.

| Single LLM call | Swarm of 5 + synthesizer |
|---|---|
| One angle, one set of blind spots | Five angles, blind spots cancel out |
| Confident hallucinations | Disagreements get surfaced |
| One answer, no calibration | Agreement score tells you *how sure* the swarm is |
| Sequential thinking | Parallel — all 5 run at once via async |

## What it does

1. You ask a question (CLI argument or text file).
2. Five Claude calls fire in parallel, each under a different persona's system prompt.
3. Each persona produces an analysis + a self-rated 1–10 confidence.
4. A **synthesizer** Claude call (bigger model) reads all five replies and produces a final consensus answer + agreement score (0–100).
5. A self-contained HTML report renders every viewpoint side by side.

## The five personas

| Persona | Role |
|---|---|
| 📐 **The Analyst** | Breaks the problem into parts, lists trade-offs, quantifies when possible |
| 🔎 **The Skeptic** | Challenges assumptions, surfaces what could go wrong |
| 🌱 **The Optimist** | Finds upside, the best-case path, opportunities others miss |
| 🛠️ **The Pragmatist** | Focuses on what's actually doable — what's the concrete next step? |
| 🎓 **The Domain Expert** | Brings deep technical knowledge of the relevant field |

Plus a **Synthesizer** that reads all five and writes the final consensus.

Edit `personas.json` to change them, add more, or build a domain-specific swarm.

## Quick start

```bash
git clone https://github.com/YOUR-USERNAME/swarm-ai.git
cd swarm-ai
pip install -r requirements.txt

cp .env.example .env
# Open .env and add: ANTHROPIC_API_KEY=sk-ant-...

# Run with a question on the command line
python swarm.py "Should we adopt Kubernetes for our 5-engineer startup?"

# Or load a long question from a file
python swarm.py --question-file my_decision.txt

# See the loaded personas
python swarm.py --list-personas
```

## Sample output

```
══════════════════════════════════════════════════════════════════════
  🐝  Swarm AI — Multi-Agent Consensus
══════════════════════════════════════════════════════════════════════

  ❓ Question:
     Should we adopt Kubernetes for our 5-engineer startup?

  🤖 Swarm members:

  📐  The Analyst  (confidence 7/10)
     [structured tradeoff analysis…]

  🔎  The Skeptic  (confidence 9/10)
     [list of failure modes, hidden costs…]

  🌱  The Optimist  (confidence 6/10)
     [upside scenario, what works well…]

  🛠️  The Pragmatist  (confidence 8/10)
     [next concrete step, what ships in 30 days…]

  🎓  The Domain Expert  (confidence 8/10)
     [field-specific knowledge…]

══════════════════════════════════════════════════════════════════════
  🧩  Consensus  (agreement score: 78/100)
══════════════════════════════════════════════════════════════════════

  ## Consensus
  At 5 engineers, Kubernetes is operational overkill. Stick with
  managed PaaS (Render, Fly.io, or AWS ECS Fargate) until you hit
  growth signals that justify K8s complexity…

  ## Strongest agreement
  - Operational burden of K8s exceeds team's current capacity
  - Managed PaaS solves 95% of the use case for 5% of the effort

  ## Real disagreements
  - Optimist sees long-term value in K8s skill investment;
    Skeptic argues that's a sunk-cost rationalization

  ## Recommended action
  Pick a managed PaaS this week, ship the first service to it
  within 14 days. Revisit K8s when team passes 12 engineers.

  ## Agreement score
  78
══════════════════════════════════════════════════════════════════════

  📄 Report saved: reports/20260106-093421.html
```

The HTML report renders the same content with each persona in their own colored card, plus a visual agreement-score bar.

## CLI flags

| Flag | What it does |
|---|---|
| `<question>` | Provide the question as positional args (in quotes for multi-word) |
| `--question-file <path>` | Load a long question from a text file |
| `--model <id>` | Claude model for the agents (default: Haiku 4.5) |
| `--list-personas` | Show the loaded personas and exit |
| `--no-report` | Terminal output only, skip the HTML report |

## How it works (the architecture)

```
              ┌──────────────────────────────────┐
              │  Your question                   │
              └────────────┬─────────────────────┘
                           │
              ┌────────────┴───────────────┐
              ▼                            ▼
   ┌─────────────────────────────────────────────────────┐
   │              5 agents in parallel                    │
   │                                                      │
   │  📐 Analyst   🔎 Skeptic   🌱 Optimist               │
   │  🛠️ Pragmatist            🎓 Domain Expert           │
   │  (each: separate system prompt + Claude call)        │
   └────────────────────────┬────────────────────────────┘
                            │
                            ▼
                ┌────────────────────────┐
                │  Synthesizer (Sonnet)  │
                │  reads all 5 replies   │
                │  finds agreement       │
                │  writes consensus      │
                └────────────┬───────────┘
                             ▼
              ┌──────────────────────────────────┐
              │  Consensus + agreement score 0–100│
              │  + HTML report                   │
              └──────────────────────────────────┘
```

Each agent runs in **parallel** via `asyncio` — so a 5-agent swarm completes in roughly the time of a single Claude call, not 5×.

## Tech

- **Python 3.10+** with `asyncio`
- **Anthropic SDK** (`AsyncAnthropic`) for parallel calls
- **python-dotenv** for clean secret handling
- **No other dependencies** — vanilla Python and HTML
- ~430 lines, single file

Default config:
- 5 agents on **Claude Haiku 4.5** (fast, cheap, ~$0.001 per question)
- Synthesizer on **Claude Sonnet 4.6** (better synthesis quality)

## Honest caveats

- **Personas are prompt-engineered, not "real" agents.** Each is a Claude call with a different system prompt. There's no separate model brain per agent. That's fine for most use cases but don't oversell it.
- **Agreement score is self-reported by the synthesizer.** It's a useful heuristic, not a calibrated probability.
- **Cost & latency.** A swarm run is 6 Claude calls (5 agents + synthesizer). At Haiku/Sonnet pricing this is cheap, but it's not free. Each call is independent — no caching across runs.
- **No web search, no external tools.** The agents only know what's in Claude's training data + your question. For research questions, layer this on top of a RAG setup.
- **Quality depends on the personas.** The default 5 work for general decisions. For specialized domains, edit `personas.json` to swap in better ones (legal, medical, security, etc.).

## Possible extensions

- Multi-round refinement (round 2: each agent sees the others' replies and revises)
- Domain-specific persona packs (legal swarm, security swarm, code-review swarm)
- Add OpenAI / Gemini agents alongside Claude (true cross-vendor swarm)
- Web UI for non-technical users
- Persistence — log every swarm run to SQLite for later review

## License

MIT — use it, fork it, ship something smarter.

---

Built by **Carl Owen E. Belen** &middot; AI Tools Specialist &middot; College Instructor (IT) &middot; [Portfolio](https://github.com/YOUR-USERNAME)
