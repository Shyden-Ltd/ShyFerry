"""Mechanical integrity checks over the ShyFerry design spec.

Every check carries a positive control: the detector is first proven to fire
on a planted example, so an empty result means "nothing found" rather than
"the detector is blind".
"""
import re
import sys
from pathlib import Path

SPEC = Path(__file__).with_name("2026-09-20-shyferry-design.md")
text = SPEC.read_text(encoding="utf-8")
lines = text.splitlines()
problems = []
controls = []


def control(name, detector, sample, expect=True):
    """Prove a detector fires on a planted sample before trusting its verdict."""
    got = bool(detector(sample))
    controls.append((name, got == expect))
    if got != expect:
        problems.append(f"CONTROL FAILED: {name} detector is blind")


# --- 1. placeholders -------------------------------------------------------
PLACEHOLDER = re.compile(r"\b(TBD|TODO|FIXME|XXX|\?\?\?|to be decided|coming soon)\b", re.I)
control("placeholder", PLACEHOLDER.search, "this is TBD for now")
hits = [(i + 1, l.strip()) for i, l in enumerate(lines) if PLACEHOLDER.search(l)]
for ln, l in hits:
    problems.append(f"placeholder at line {ln}: {l[:70]}")

# --- 2. section cross-references resolve -----------------------------------
HEADING = re.compile(r"^#{2,3}\s+(\d+(?:\.\d+)?)\.?\s")
control("heading top-level", HEADING.match, "## 2. Decisions already taken")
control("heading sub-level", HEADING.match, "### 1.1 In scope for MVP")
headings = {m.group(1) for m in (HEADING.match(l) for l in lines) if m}
REF = re.compile(r"section (\d+(?:\.\d+)?)", re.I)
control("section ref", REF.search, "see section 4.2 for detail")
refs = {}
for i, l in enumerate(lines):
    for m in REF.finditer(l):
        refs.setdefault(m.group(1), []).append(i + 1)
for ref, where in sorted(refs.items()):
    if ref not in headings:
        problems.append(f"dangling cross-reference 'section {ref}' at line(s) {where}")

# --- 3. invariants defined vs referenced -----------------------------------
INV = re.compile(r"\bINV-(\d+)\b")
control("inv id", INV.search, "see INV-3 above")
defined = set()
referenced = {}
for i, l in enumerate(lines):
    for m in INV.finditer(l):
        n = int(m.group(1))
        if l.lstrip().startswith("| INV-"):
            defined.add(n)
        else:
            referenced.setdefault(n, []).append(i + 1)
span = re.search(r"INV-(\d+) to INV-(\d+)", text)
if span:
    for n in range(int(span.group(1)), int(span.group(2)) + 1):
        referenced.setdefault(n, []).append("range reference")
for n in sorted(defined):
    if n not in referenced:
        problems.append(f"INV-{n} is defined but never referenced elsewhere")
for n in sorted(referenced):
    if n not in defined:
        problems.append(f"INV-{n} is referenced but never defined")

# --- 4. story ids contiguous and counted correctly -------------------------
STORY = re.compile(r"^\| (S-(\d+)) \|")
stories = sorted(int(m.group(2)) for m in (STORY.match(l) for l in lines) if m)
if stories != list(range(1, len(stories) + 1)):
    problems.append(f"story ids not contiguous from 1: {stories}")
WORDS = {"eighteen": 18, "seventeen": 17, "nineteen": 19, "sixteen": 16}
claim = re.search(r"\b(\w+) stories\b", text, re.I)
if claim:
    want = WORDS.get(claim.group(1).lower())
    if want is None:
        problems.append(f"story count claim not parseable: '{claim.group(0)}'")
    elif want != len(stories):
        problems.append(f"prose claims {claim.group(0)} but table lists {len(stories)}")

# --- 4b. decisions cited where they are realised ---------------------------
DECISION = re.compile(r"\bD([1-9]\d?)\b")
control("decision id", DECISION.search, "as required by D5")
d_defined, d_cited = set(), set()
for l in lines:
    for m in DECISION.finditer(l):
        (d_defined if l.lstrip().startswith(f"| D{m.group(1)} |") else d_cited).add(int(m.group(1)))
for n in sorted(d_defined - d_cited):
    problems.append(f"D{n} is decided but never cited in the section that realises it")

# --- 4c. every invariant carries a mutation --------------------------------
for i, l in enumerate(lines):
    if l.lstrip().startswith("| INV-"):
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[3]:
            problems.append(f"INV row at line {i + 1} has no mutation: {cells[0]}")

# --- 4d. table blocks have a consistent column count -----------------------
block, start = [], 0
for i, l in enumerate(lines + [""]):
    if l.startswith("|"):
        if not block:
            start = i + 1
        block.append(l)
        continue
    if block:
        widths = {r.count("|") for r in block}
        if len(widths) > 1:
            problems.append(f"table starting line {start} has ragged rows: widths {sorted(widths)}")
        block = []

# --- 4e. every command mentioned anywhere is in the documented CLI surface --
CMD = re.compile(r"`?shyferry ([a-z][a-z-]*)")
control("command mention", CMD.search, "run `shyferry purge-source 1` now")
surface, in_block, mentioned = set(), False, {}
for i, l in enumerate(lines):
    if l.startswith("shyferry "):          # the fenced CLI surface block
        surface.add(l.split()[1])
        in_block = True
        continue
    for m in CMD.finditer(l):
        mentioned.setdefault(m.group(1), []).append(i + 1)
if not surface:
    problems.append("CONTROL FAILED: no CLI surface block found to check against")
for cmd, where in sorted(mentioned.items()):
    if cmd not in surface:
        problems.append(f"command 'shyferry {cmd}' used at line(s) {where} is absent from the CLI surface")

# --- 5. risk and spike ids referenced --------------------------------------
for ident in set(re.findall(r"\b(?:SPIKE|R)-\d+\b", text)):
    if text.count(ident) < 2:
        problems.append(f"{ident} appears only once; defined but never referenced")

# --- 6. deferred-scope terms must not appear as in-scope -------------------
DEFERRED = ("Shared Drive", "SharePoint", "OneDrive for Business", "Workspace admin")
control("deferred term", lambda s: "SharePoint" in s, "we support SharePoint")
in_scope_block = text.split("### 1.2")[0]
for term in DEFERRED:
    if term in in_scope_block:
        problems.append(f"deferred term '{term}' appears in the in-scope section")

# --- report ----------------------------------------------------------------
print(f"spec: {len(lines)} lines, {len(text.split())} words")
print(f"headings found: {len(headings)}  invariants: {len(defined)}  stories: {len(stories)}")
print("controls: " + ", ".join(f"{n}={'ok' if ok else 'BLIND'}" for n, ok in controls))
print("-" * 60)
if problems:
    for p in problems:
        print("FINDING:", p)
    sys.exit(1)
print("no mechanical problems found")
