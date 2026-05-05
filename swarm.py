"""
🐝  Swarm AI — Multi-Agent Consensus System
============================================
Ask one question. Five AI agents with different personas analyze it independently
and in parallel. A sixth "synthesizer" agent reads all five viewpoints and writes
a consensus answer with a calibrated agreement score.

Why multi-agent?
----------------
A single LLM gives you one perspective and can hallucinate confidently. A swarm of
agents with different vantage points (skeptic, optimist, pragmatist, etc.) surfaces
disagreements, finds blind spots, and produces a more reliable consensus than any
single call. This is the "Mixture of Agents" pattern, applied as a CLI.

Quick start
-----------
    pip install -r requirements.txt
    cp .env.example .env  # add ANTHROPIC_API_KEY
    python swarm.py "Should I take a new job offer that pays 30% more but requires relocation?"
    python swarm.py --question-file my_question.txt
    python swarm.py --list-personas

Output
------
    Terminal summary of every agent's view + the final consensus, plus a
    self-contained HTML report in reports/<timestamp>.html with each
    persona's reply in their own colored card.

Author
------
Carl Owen E. Belen — https://github.com/YOUR-USERNAME
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SYNTHESIZER_MODEL = "claude-sonnet-4-6"  # bigger model for the final consensus
MAX_TOKENS_AGENT = 800
MAX_TOKENS_SYNTHESIS = 1500
PERSONAS_FILE = Path(__file__).resolve().parent / "personas.json"


# ============================================================
# 🎭  Personas
# ============================================================
@dataclass
class Persona:
    name: str
    role: str
    color: str          # hex, used in HTML report
    emoji: str
    system_prompt: str

    def label(self) -> str:
        return f"{self.emoji}  {self.name}"


def load_personas() -> dict[str, Persona]:
    if not PERSONAS_FILE.exists():
        raise FileNotFoundError(f"Persona file not found: {PERSONAS_FILE}")
    data = json.loads(PERSONAS_FILE.read_text(encoding="utf-8"))
    return {key: Persona(**val) for key, val in data.items()}


# ============================================================
# 🤖  One agent's reply
# ============================================================
@dataclass
class AgentReply:
    persona: Persona
    answer: str
    confidence: int  # 1–10 self-rated
    raw: str         # full raw model output

    def short(self) -> str:
        s = self.answer.strip()
        if len(s) > 240:
            s = s[:237] + "…"
        return s


# ============================================================
# 🧠  Calling Claude (one agent)
# ============================================================
async def run_agent(
    client: AsyncAnthropic,
    persona: Persona,
    question: str,
    model: str,
) -> AgentReply:
    """Send the question to Claude under one persona's system prompt."""
    user_message = (
        f"Question to analyze:\n\n{question}\n\n"
        f"Provide your analysis in 4–8 sentences. End with a single line:\n"
        f"CONFIDENCE: <integer from 1 to 10>\n"
        f"where 10 = certain and 1 = pure guess."
    )
    msg = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS_AGENT,
        system=persona.system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = msg.content[0].text

    # Parse the confidence line
    confidence = 5
    m = re.search(r"CONFIDENCE\s*:\s*(\d+)", raw, re.IGNORECASE)
    if m:
        try:
            confidence = max(1, min(10, int(m.group(1))))
        except ValueError:
            pass

    # Strip the confidence line for the displayed answer
    answer = re.sub(r"\n?\s*CONFIDENCE\s*:\s*\d+\s*$", "", raw,
                    flags=re.IGNORECASE).strip()

    return AgentReply(persona=persona, answer=answer,
                      confidence=confidence, raw=raw)


# ============================================================
# 🐝  The swarm
# ============================================================
async def run_swarm(question: str, personas: list[Persona],
                    model: str) -> list[AgentReply]:
    """Run every persona in parallel, return their replies."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add yours.")
    client = AsyncAnthropic(api_key=api_key)
    tasks = [run_agent(client, p, question, model) for p in personas]
    return await asyncio.gather(*tasks)


# ============================================================
# 🧩  The synthesizer
# ============================================================
SYNTHESIZER_PROMPT = """You are the Synthesizer. Five expert personas have independently analyzed a question. Your job:

1. Read every persona's analysis carefully.
2. Identify points of strong agreement, points of disagreement, and any blind spots that emerged collectively.
3. Produce a final consensus answer that integrates the strongest insights from each persona while resolving (or honestly noting) disagreements.

Your output must follow this exact structure:

## Consensus
<3–5 sentence direct answer to the question, integrating the swarm's best thinking>

## Strongest agreement
- <bullet point — what the swarm agreed on>
- <bullet point>

## Real disagreements
- <bullet — only include if the personas genuinely disagreed; otherwise write "None — the swarm aligned closely.">

## Recommended action
<one short paragraph: the most pragmatic next step>

## Agreement score
<integer 0–100 — how much the personas agreed overall. 100 = unanimous, 0 = total disagreement>"""


async def synthesize(question: str, replies: list[AgentReply],
                     model: str = SYNTHESIZER_MODEL) -> tuple[str, int]:
    """Call a Claude synthesizer with all 5 agents' replies, return (consensus_md, score)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = AsyncAnthropic(api_key=api_key)

    panel = [f"# Original question\n\n{question}\n", "# Swarm members' analyses\n"]
    for r in replies:
        panel.append(f"## {r.persona.name} — confidence {r.confidence}/10")
        panel.append(r.answer)
        panel.append("")
    panel.append("Now synthesize per the system instructions.")

    msg = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS_SYNTHESIS,
        system=SYNTHESIZER_PROMPT,
        messages=[{"role": "user", "content": "\n".join(panel)}],
    )
    text = msg.content[0].text

    # Pull the agreement score out
    score = 50
    m = re.search(r"Agreement\s+score\s*\n*\s*(\d+)", text, re.IGNORECASE)
    if m:
        try:
            score = max(0, min(100, int(m.group(1))))
        except ValueError:
            pass

    return text, score


# ============================================================
# 🖨️  Terminal output
# ============================================================
class K:
    CY = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"
    M = "\033[35m"; B = "\033[94m"; W = "\033[97m"; DIM = "\033[2m"
    BOLD = "\033[1m"; END = "\033[0m"


def c(t, color):
    return f"{color}{t}{K.END}"


def print_summary(question: str, replies: list[AgentReply],
                  consensus: str, score: int):
    print()
    print(c("═" * 72, K.DIM))
    print(c("  🐝  Swarm AI — Multi-Agent Consensus", K.BOLD + K.CY))
    print(c("═" * 72, K.DIM))
    print()
    print(c("  ❓ Question:", K.BOLD))
    print(f"     {question}")
    print()
    print(c("  🤖 Swarm members:", K.BOLD))
    for r in replies:
        print(c(f"\n  {r.persona.label()}  (confidence {r.confidence}/10)", K.BOLD + K.B))
        for line in r.short().split("\n"):
            print(c(f"     {line}", K.W))
    print()
    print(c("═" * 72, K.DIM))
    print(c(f"  🧩  Consensus  (agreement score: {score}/100)", K.BOLD + K.G))
    print(c("═" * 72, K.DIM))
    print()
    for line in consensus.split("\n"):
        print(c(f"  {line}", K.W))
    print()
    print(c("═" * 72, K.DIM))


# ============================================================
# 📄  HTML report
# ============================================================
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Swarm AI Consensus Report</title>
<style>
:root {{ --bg: #0f0f10; --card: #1a1a1a; --text: #f0f0f0; --muted: #888; --accent: #a3e635; }}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; margin: 0; line-height: 1.6; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 3rem 2rem 5rem; }}
h1 {{ font-size: 2.5rem; margin: 0 0 0.4rem; letter-spacing: -0.02em; }}
.subtitle {{ color: var(--muted); margin-bottom: 2.5rem; }}
.eyebrow {{ color: var(--accent); text-transform: uppercase; letter-spacing: 2px; font-size: 0.78rem; font-weight: 700; margin-bottom: 0.4rem; }}
.question-card {{ background: var(--card); border: 1px solid #222; border-radius: 14px; padding: 1.75rem 2rem; margin-bottom: 2rem; }}
.question-card .q-label {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 1.6px; margin-bottom: 0.5rem; }}
.question-card .q-text {{ font-size: 1.15rem; line-height: 1.5; }}
.consensus-card {{ background: var(--card); border: 2px solid var(--accent); border-radius: 14px; padding: 2rem 2.25rem; margin-bottom: 2.5rem; position: relative; }}
.consensus-card .stamp {{ position: absolute; top: -12px; left: 24px; background: var(--accent); color: #0a2010; font-weight: 700; font-size: 0.8rem; letter-spacing: 1.4px; padding: 0.25rem 0.85rem; border-radius: 30px; text-transform: uppercase; }}
.consensus-md h2 {{ color: var(--accent); font-size: 1.05rem; text-transform: uppercase; letter-spacing: 1.6px; margin-top: 1.5rem; margin-bottom: 0.5rem; }}
.consensus-md h2:first-child {{ margin-top: 0; }}
.consensus-md ul {{ padding-left: 1.5rem; }}
.score-bar {{ background: #2a2a2a; border-radius: 50px; height: 14px; overflow: hidden; margin-top: 1rem; }}
.score-bar-fill {{ background: linear-gradient(90deg, #fb7185, #fbbf24, var(--accent)); height: 100%; border-radius: 50px; }}
.score-label {{ display: flex; justify-content: space-between; color: var(--muted); font-size: 0.85rem; margin-top: 0.4rem; }}
h2.section {{ font-size: 1.2rem; color: var(--muted); text-transform: uppercase; letter-spacing: 2px; font-weight: 700; margin: 2.5rem 0 1rem; }}
.agents {{ display: grid; grid-template-columns: 1fr; gap: 1rem; }}
.agent {{ background: var(--card); border: 1px solid #222; border-left: 4px solid var(--agent-color, var(--accent)); border-radius: 12px; padding: 1.5rem 1.75rem; }}
.agent-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.85rem; }}
.agent-name {{ font-weight: 700; font-size: 1.1rem; color: var(--agent-color, var(--accent)); }}
.agent-role {{ color: var(--muted); font-size: 0.88rem; margin-top: 0.15rem; }}
.confidence {{ display: inline-flex; align-items: center; gap: 0.5rem; background: #232323; border-radius: 50px; padding: 0.35rem 0.85rem; font-size: 0.8rem; font-weight: 600; }}
.confidence-bar {{ width: 60px; height: 6px; background: #333; border-radius: 50px; overflow: hidden; }}
.confidence-bar-fill {{ height: 100%; background: var(--agent-color, var(--accent)); }}
.agent-answer {{ color: #ddd; white-space: pre-wrap; line-height: 1.65; }}
footer {{ color: var(--muted); border-top: 1px solid #222; padding-top: 1.5rem; margin-top: 3rem; font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="container">
  <div class="eyebrow">Swarm AI Consensus</div>
  <h1>Multi-agent analysis</h1>
  <div class="subtitle">{n_agents} personas · synthesized by Claude · generated {generated_at}</div>

  <div class="question-card">
    <div class="q-label">Question</div>
    <div class="q-text">{question}</div>
  </div>

  <div class="consensus-card">
    <div class="stamp">Consensus</div>
    <div class="consensus-md">{consensus_html}</div>
    <div class="score-bar"><div class="score-bar-fill" style="width: {score}%;"></div></div>
    <div class="score-label"><span>Disagreement</span><span><strong style="color: var(--accent);">{score}/100</strong> agreement</span><span>Unanimous</span></div>
  </div>

  <h2 class="section">Individual viewpoints</h2>
  <div class="agents">{agents_html}</div>

  <footer>
    Generated by <strong>Swarm AI</strong>. Each persona produced an independent analysis under a different system prompt; the consensus is a separate Sonnet call that reads all five viewpoints. Treat as a thinking aid, not gospel.
  </footer>
</div>
</body>
</html>
"""


def md_to_html_lite(md: str) -> str:
    """Tiny Markdown subset: headers, bullets, paragraphs."""
    lines = md.split("\n")
    out = []
    in_ul = False
    for line in lines:
        ls = line.strip()
        if not ls:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue
        if ls.startswith("## "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<h2>{ls[3:].strip()}</h2>")
        elif ls.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{ls[2:].strip()}</li>")
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{ls}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def render_report(question: str, replies: list[AgentReply],
                  consensus: str, score: int, output_path: Path | str):
    agents_blocks = []
    for r in replies:
        conf_pct = r.confidence * 10
        agent_html = (
            f'<div class="agent" style="--agent-color: {r.persona.color};">'
            f'  <div class="agent-header">'
            f'    <div>'
            f'      <div class="agent-name">{r.persona.emoji}  {r.persona.name}</div>'
            f'      <div class="agent-role">{r.persona.role}</div>'
            f'    </div>'
            f'    <div class="confidence">'
            f'      <span>conf {r.confidence}/10</span>'
            f'      <div class="confidence-bar"><div class="confidence-bar-fill" '
            f'           style="width: {conf_pct}%;"></div></div>'
            f'    </div>'
            f'  </div>'
            f'  <div class="agent-answer">{r.answer}</div>'
            f'</div>'
        )
        agents_blocks.append(agent_html)

    html = HTML.format(
        n_agents=len(replies),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        question=question.replace("<", "&lt;"),
        consensus_html=md_to_html_lite(consensus),
        score=score,
        agents_html="\n".join(agents_blocks),
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ============================================================
# 🚀  CLI
# ============================================================
async def run(question: str, model: str, no_report: bool):
    print(c("  → loading personas …", K.DIM))
    personas = list(load_personas().values())
    print(c(f"  → dispatching {len(personas)} agents in parallel …", K.DIM))
    replies = await run_swarm(question, personas, model)
    print(c("  → synthesizing consensus …", K.DIM))
    consensus, score = await synthesize(question, replies)

    print_summary(question, replies, consensus, score)

    if not no_report:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = Path("reports") / f"{timestamp}.html"
        path = render_report(question, replies, consensus, score, out)
        print(c(f"  📄 Report saved: {path.absolute()}", K.G))
        print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Swarm AI — multi-agent consensus system."
    )
    parser.add_argument("question", nargs="*",
                        help="The question for the swarm to analyze.")
    parser.add_argument("--question-file", type=str,
                        help="Path to a text file containing the question.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model for the agents (default: {DEFAULT_MODEL})")
    parser.add_argument("--list-personas", action="store_true",
                        help="Show the loaded personas and exit.")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip the HTML report (terminal only).")
    args = parser.parse_args()

    if args.list_personas:
        personas = load_personas()
        print(c("📋  Personas in this swarm:", K.BOLD + K.CY))
        for key, p in personas.items():
            print(c(f"\n  {p.emoji}  {p.name}", K.BOLD + K.B))
            print(c(f"     Role: {p.role}", K.W))
            print(c(f"     Color: {p.color}", K.DIM))
        print()
        sys.exit(0)

    # Resolve question
    if args.question_file:
        question = Path(args.question_file).read_text(encoding="utf-8").strip()
    elif args.question:
        question = " ".join(args.question)
    else:
        print(c("⚠️  Provide a question (in quotes) or use --question-file.", K.R))
        print(c('    Example: python swarm.py "Should we adopt Kubernetes?"', K.DIM))
        sys.exit(1)

    if not question:
        print(c("⚠️  Empty question.", K.R))
        sys.exit(1)

    asyncio.run(run(question, args.model, args.no_report))


if __name__ == "__main__":
    main()
