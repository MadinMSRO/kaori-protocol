# Handoff: Kaori Flow research and Liminal Phase 1

For a new Claude Code session. Read this first, then the files it points to. It tells you how to set up the
environment, where things are, what has been decided, and how to work with Madin.

---

## 1. Environment configuration

### Repositories (attach both to the session)

| Repo | Branch to check out | What it is |
|---|---|---|
| `MadinMSRO/kaori-protocol` | `research/kaori-flow-sim` (this doc) | The protocol: `packages/kaori-{spec,truth,flow,db,api}`, whitepaper, ClaimType YAMLs |
| `MadinMSRO/liminal-mobile` | `declutter` | The Expo React Native app (`mobile/`) |

Other kaori-protocol branch: `feat/sky-cover-claim-type`. It has the sky-cover ClaimType, the zero-shot
generalist and settlement scoring against the compiled claim. MSRO still needs to deploy it (the API and
`Dockerfile.generalist`). `research/kaori-flow-sim` branches from it.

### Network access (environment settings → Network access → allowed domains)

| Host | Why | Required? |
|---|---|---|
| `github.com`, `api.github.com` | clone and push | yes |
| `pypi.org`, `files.pythonhosted.org` | Python packages | yes |
| `download.pytorch.org` | CPU-only torch wheel (about 200 MB, against about 2.5 GB for the CUDA build from PyPI) | strongly recommended |
| `openaipublic.azureedge.net` | CLIP ViT-B/32 OpenAI weights (the official source open_clip uses) | yes, or the fallback below |
| `clip-as-service.s3.us-east-2.amazonaws.com` | fallback copy of the same weights (identical SHA-256) | fallback |
| `registry.npmjs.org` | the mobile app's npm packages | for mobile work |
| `expo.dev`, `api.expo.dev` | EAS builds of the APK (`probe-sky-test` profile) | for APK builds |
| `huggingface.co` | blocked last time. Not needed if the weights come from above | optional |

### Setup script (environment settings → Setup script)

```bash
#!/bin/bash
set -euo pipefail

# Python 3.11 venv for Kaori and the simulators
python3 -m venv /opt/kvenv
/opt/kvenv/bin/pip install -q --upgrade pip
# CPU torch (falls back to PyPI if download.pytorch.org is not allowed)
/opt/kvenv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch torchvision \
  || /opt/kvenv/bin/pip install -q torch torchvision
/opt/kvenv/bin/pip install -q numpy open_clip_torch ftfy regex tqdm pillow pyyaml \
  fastapi "uvicorn[standard]" httpx python-multipart requests sqlalchemy "pydantic>=2" python-jose pytest

# CLIP ViT-B/32 OpenAI weights, verified by hash (Kaori's generalist pins this file)
mkdir -p /opt/clipw
SHA=40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af
curl -fsSL -o /opt/clipw/ViT-B-32.pt "https://openaipublic.azureedge.net/clip/models/$SHA/ViT-B-32.pt" \
  || curl -fsSL -o /opt/clipw/ViT-B-32.pt "https://clip-as-service.s3.us-east-2.amazonaws.com/models-436c69702d61732d53657276696365/torch/ViT-B-32.pt"
echo "$SHA  /opt/clipw/ViT-B-32.pt" | sha256sum -c -
```

### Environment variables

```
KAORI_CLIP_CACHE=/opt/clipw          # the generalist and ai_check.py load ViT-B-32.pt from here
KAORI_SCHEMA_PATH=<kaori-protocol>/packages/kaori-spec/schemas
PATH=/opt/kvenv/bin:$PATH
```

### First steps inside the session (they need the repos, so they are not in the setup script)

```bash
cd <kaori-protocol>
pip install -q --no-deps -e packages/kaori-spec -e packages/kaori-truth -e packages/kaori-flow -e packages/kaori-db -e packages/kaori-api
pytest -q                               # protocol tests
cd research/flow-sim && python trust.py # latest simulator (about 3 min, 4 cores)

cd <liminal-mobile>/mobile && npm ci && npx tsc --noEmit && npm test
```

Notes:
- The machine has 4 cores. Simulators use `multiprocessing.Pool(4)`. Full arenas take 3 to 45 minutes. Run
  long ones with `run_in_background` and a long timeout (the default 30 minutes killed one run).
- The system `python3` has no numpy. Use `/opt/kvenv/bin/python`.
- To kill processes, use `ps aux | grep "[p]attern"`. A bare `pkill -f` matched its own shell (exit 144).
- Disk is a fixed allowance. PyPI's CUDA torch alone is about 2.5 GB, which is why the CPU index matters.
- **Rejected tool calls sometimes still ran.** Three times, a Bash call the user rejected had already
  written files or started processes. After any rejection, check for leftover files and processes and undo
  them.

---

## 2. Where things are

### `research/flow-sim/` (this folder): the Kaori Flow simulators, in the order they were built

| File | What it tested | Status |
|---|---|---|
| `sim.py`, `server.py`, `ai_check.py` | Full stack: a local Kaori sidecar on :8787 (tokens `tok-X`, `ai-generalist`) and the real CLIP on photos in `photos/` | CLIP zero-shot: 8/8 skies pass, 4/4 non-skies rejected |
| `physics_sim.py`, `sweep.py`, `evo.py` | Today's Flow against natural laws (evolutionary search) | Today's Flow rewards consensus, not truth. About 30% wrong under colluding rings |
| `coevo.py`, `frontier.py` | Attackers co-evolved against the laws; safety versus yield | The attack suite and hall of fame live in `coevo-result.json` |
| `topo.py`, `emerge.py` | Hand-picked topologies, then **emergent** bonds (co-presence beyond chance) | Rings knot by themselves |
| `sense.py`, `agents.py` | Everything is an agent; the provenance agent; the value space | Provenance is decisive for yield |
| `seed.py`, `blind.py` | Constants learned instead of tuned; blind validators | The untuned seed matches the evolved champion |
| `arena.py` | Every earlier champion against adaptive attackers | Found the real-photo-lie hole in my claims-vote model |
| `flow7.py` | Madin's compile flow (evidence-anchored, signals after compile) | Superseded by the two below |
| `captcha.py` | Captcha-style validator pool, farms, two lanes | Farms knot; random assignment does most of the work |
| `hybrid.py` | An earned-reliability gate for implicit consensus | **Wrong approach (violates Rule 4). Superseded by `trust.py`** |
| **`trust.py`** | **Rules 3 and 4 made literal: global standing S∈[0,1000], local trust per claim, one trust score per value (evidence in log-odds), implicit consensus, escalation to captcha validators, contested = `INCONCLUSIVE` with penalty** | **The current model** |
| `*-run.txt`, `*-result.json` | Outputs of each run | |
| `pending-generalist-relevance.patch` | Uncommitted edits to `kaori-api` `generalist.py` and `validation.py` (per-observation relevance on `ValidationVote`), also kept in `git stash` on `feat/sky-cover-claim-type` | Intended: keep the relevance **data** and remove the threshold-based confidence rule. Not applied |
| `*.test.ts` | Earlier contract tests. They import `../src/...`, so they run from `liminal-mobile/mobile/scripts/` | `scripts/kaori-sky-contract.ts` in liminal-mobile is the maintained one |

### Kaori, the spec you must respect
- `packages/kaori-spec/FLOW_SPEC.md`: **the 7 Rules of Trust** (normative).
- `kaori_protocol_whitepaper.md`: the 7 Laws of Truth (§6), Rules (§6.1), physics (§17), attacks (§18).
- `packages/kaori-spec/schemas/earth/sky_cover_v1.yaml`: the IAC test ClaimType, including
  `implicit_consensus` (only `min_observations` is implemented; see `INTEGRATION.md`).
- `packages/kaori-truth/src/kaori_truth/primitives/truthstate.py`: statuses. `INCONCLUSIVE` is final and signed.
- `packages/kaori-flow/src/kaori_flow/settlement.py`: signals only for VERIFIED_TRUE and VERIFIED_FALSE today.

### Liminal (`liminal-mobile/mobile`)
- Tabs: tonight, map, community, you. Store: zustand with persist.
- Live mode: `src/state/live.ts`, `src/services/liveReport.ts` (liveTruthKey, livePayload).
- Map: `src/screens/Map.tsx` (Earth, Ocean and Space lenses, epic mode, Around you).
- IAC sky test: `docs/SKY_TEST.md`, `scripts/kaori-sky-contract.ts`. APK profile: `probe-sky-test`.
- `EXPO_PUBLIC_UI_PREVIEW_LIVE` is only for screenshots.

---

## 3. What has been decided (Madin's design, which the simulations back)

**Layers.** 7 Laws of Truth (TRUTH) · 7 Rules of Trust (FLOW) · 7 Principles of Emergence (FlowPolicy design).
The Principles sit *under* the Rules. They don't replace them.

**7 Principles of Emergence (draft):**
1. Evidence must be real (the provenance agent: EXIF, attestation, in-app capture).
2. Witnesses must be independent (bonds from shared presence and shared error beyond chance; a knot counts as one).
3. Judges are blind (validators see each item and a provenance badge, never claims, hex or TruthKey).
4. Truth forms at the finest grain its weight supports (value space; band or pair truths).
5. Learn only from signals an attacker can't author.
6. Nothing is tuned (constants are learned, or derived from stakes: the threshold is λ/(1+λ)).
7. Nothing is thrown away.

**Rules 3 and 4 are firm.** Standing is ONE global number per agent. Trust is local: standing plus the local
topology of that claim gives ONE trust score per claim and value. Don't invent side gates or extra
reliability numbers. That was a mistake (see `hybrid.py`).

**Compile flow** (Madin's spec, as in `trust.py`):
1. Observers submit a photo and a claim.
2. Validators assess **each piece of evidence** against the ClaimType, blind to the claims, like captcha
   micro-tasks. Random assignment, several per item. Validators never learn the hex or TruthKey, so
   collusion is hard.
3. **Implicit consensus**: the leading value's local trust passes `min_network_trust` and dominates →
   VERIFIED (basis IMPLICIT_CONSENSUS). Disagreement is not special: high trust outweighs.
4. Otherwise it escalates to validators, and the truth compiles from the evidence.
5. Still split when the window closes → **contested (`INCONCLUSIVE`) is itself a truth**, signed, and it
   backpropagates **a penalty signal to every observer**.
6. After compilation, signals go to every agent. A real photo sent with a conflicting claim is penalised.

**Everything is an agent**, including the AI, sensors (provenance), validators, the FlowPolicy and
**ClaimTypes** (they earn standing; versions compete).

**Lanes are set in the ClaimType**: critical = AI plus captcha humans; normal = AI only. The ClaimType also
sets the stakes, validators per item and the implicit-consensus fields.

**Recompiling**: old observations can be compiled with new ClaimTypes into new TruthStates. **History is
never deleted** (new tags on the same commits). "Git for the real world": observations are commits,
TruthStates are signed releases, trust decides merges, contested is a merge conflict. Liminal is to Kaori
what GitHub is to git.

**Identity cost** (phone OTP, device attestation) for observers AND validators is Liminal's job. Every
simulation came back to it.

## 4. Latest results (`trust-run.txt`, simulated world, 4 fresh seeds)

- 0.91 right, 1.7% wrong, 5% contested, AUC 0.83. Attacker standing collapses (cabal about 12, ring about
  23; careful observers 900 to 1000).
- Validator load falls from 68% to 57% over the run as implicit consensus unlocks.
- **The contest penalty (none, mild or full) made no measurable difference** except costing honest
  observers a little standing (956 → 938). Madin wants a penalty. Keep it, and watch it in real data.
- **Open hole:** a patient farm (11 of 40 validators, rare signed attacks) plus sleepers get 7.1% wrong
  through, because their lies are too sparse to form shared-error bonds. Candidate fixes: identity cost for
  validators, a larger pool, more validators per critical item (a ClaimType field).
- Key finding from the aggregation: trust per value must add as **evidence (log-odds of standing)**, not a
  raw sum. A raw sum let many weak fake items outweigh a few real ones (ring wrong 6% → 0.4%).

Caveat for everything: the world model's assumptions dominate the numbers. Those are the provenance pass
rates (95% real, 15% fake), AI accuracy (about 0.8) and validator accuracy (0.9, lazy 0.5). The IAC sky test
must log real values.

## 5. Open items and next steps

1. **IAC Phase 1 (Antalya, `earth.sky_cover.v1`)**: MSRO deploys `feat/sky-cover-claim-type` (the API and
   the generalist service), then a live-server test in Malé, then beta testers. Log provenance outcomes,
   AI confidence and validator answers from day one.
2. Implement `trust.py`'s model as a Kaori FlowPolicy and settlement path:
   - signals for `INCONCLUSIVE`;
   - `implicit_consensus` fields actually enforced (they're specced but unimplemented);
   - replace the "implicit ratify" (everyone CORRECT when there is no claim), which breaks Principle 5;
   - drop `override_if_authority_present` (it breaks Rule 2).
3. Decide what to do with `pending-generalist-relevance.patch` (keep the data, drop the threshold rule).
4. The flood ClaimType needs the same zero-shot treatment as sky cover, with real flood photos.
5. Draft the 7 Principles of Emergence section for FLOW_SPEC and the whitepaper. Madin asked about this and
   it isn't done. Note the tension with Rule 3's single scalar (the evidence model needed more internally).
   Madin holds Rule 3 firm, so derive everything from S.
6. Privacy: evidence is content-addressed and storage uses a hashed reporter ID (unsalted SHA-256, so it can
   be recomputed), but the ledger stores `reporter_id` directly. Consider explicit
   "history permanent, identity separable" wording (crypto-shredding of the link between agent and person).

## 6. How to work with Madin

- Madin is the President of MSRO. Be direct, principled and honest about results, including null results.
- **Confirm your understanding before building** when Madin describes a mechanism. Several times I built the
  wrong thing and Madin stopped the tool. Restate the flow in numbered steps, ask the one or two questions that
  matter, then build.
- Principles Madin set: no scenario rules; a simple single topological approach designed for emergence; laws
  are derived from topology; when stuck, look to nature and physics; everything is an agent; every action
  generates a signal; don't rely on seeding; the Rules of Trust are normative.
- Use "crews", never "squads". Sentry, crews and alliance stay.
- Notes: when Madin asks to note, capture or remember something, save a markdown file in the Obsidian vault
  ("Second Brain" folder in Google Drive). Read `System/Claude Context.md` there first and follow it (real .md
  files, never Google Docs).
- Git: commit and push only when asked. Don't open PRs unless asked. Don't put model names in commits.
