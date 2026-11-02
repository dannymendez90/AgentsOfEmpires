"""Basic checks for a .per file before loading it in the game.

Flags unbalanced parentheses, unknown commands, unknown bare names, and rules
longer than any rule in the stock AI. It's a sanity check, not a full
validator: the in-game load is still the real test.

    .venv/Scripts/python custom1/lint_per.py custom1/c1_enemy/overlord.per
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "aoe2-ai-parser"
STOCK = ROOT / "docs" / "Promisory"

commands = {c["name"] for c in json.load(open(DOCS / "airef-command-inventory.json", encoding="utf-8"))["commands"]}
known = set(commands) | {"defrule", "defconst", "load", "or", "and", "not", "nand", "nor", "true", "false"}
for p in json.load(open(DOCS / "airef-parameter-inventory.json", encoding="utf-8"))["parameters"]:
    for v in p.get("value_list", []):
        known.add(v["name"].rstrip("*"))
for s in json.load(open(DOCS / "airef-strategic-number-inventory.json", encoding="utf-8"))["strategic_numbers"]:
    known.add(s["name"])


def strip_comments(text):
    return re.sub(r'("[^"]*")|;[^\n]*', lambda m: m.group(1) or "", text)


def blank_strings(text):
    return re.sub(r'"[^"]*"', '""', text)


def rules(text):
    """Yield (number of '=>', number of facts + actions) for each defrule."""
    text = blank_strings(strip_comments(text))
    i = 0
    while (i := text.find("(defrule", i)) >= 0:
        depth, children, j = 0, 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
                children += depth == 2
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield text[i:j].count("=>"), children
        i = j


stock_max = max(n for f in STOCK.glob("*.per") for _, n in rules(f.read_text(encoding="latin-1")))


def check(path):
    raw = Path(path).read_text(encoding="utf-8")
    text = blank_strings(strip_comments(raw))
    problems = []

    depth = 0
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            problems.append("extra ')'")
            depth = 0
    if depth:
        problems.append(f"{depth} unclosed '('")

    consts = set(re.findall(r"\(defconst\s+([\w-]+)", text))
    for cmd in set(re.findall(r"\(\s*([a-z][\w-]*)", text)):
        if cmd not in known:
            problems.append(f"unknown command: {cmd}")
    for tok in set(re.findall(r"(?<![\w:-])([a-z][\w-]*)(?![\w:-])", text)):
        if tok not in known and tok not in consts:
            problems.append(f"unknown name: {tok}")

    found = list(rules(raw))
    for n, (arrows, size) in enumerate(found, 1):
        if arrows != 1:
            problems.append(f"rule {n}: has {arrows} '=>'")
        if size > stock_max:
            problems.append(f"rule {n}: {size} facts+actions, more than any stock rule ({stock_max})")

    biggest = max((s for _, s in found), default=0)
    print(f"{path}: {len(found)} rules, {len(consts)} constants, biggest rule {biggest} (stock max {stock_max})")
    for p in sorted(problems):
        print("  PROBLEM:", p)
    if not problems:
        print("  OK")
    return not problems


if __name__ == "__main__":
    results = [check(p) for p in sys.argv[1:]]
    sys.exit(0 if all(results) else 1)
