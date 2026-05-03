# Markland Monetization Strategy — Design

**Date:** 2026-05-03
**Status:** Draft for review
**Target:** $25K MRR, 12 months from launch

## Goal

Define a pricing model and tier structure that:

1. Reaches **$25K MRR within 12 months** of launch.
2. Is reachable through a blend of self-serve adoption + a small number of team/SMB-enterprise contracts (founder-sales-friendly, not a full sales org).
3. Aligns price with Markland's wedge: a **collaborative knowledge surface where humans and agents are equal editors** (H2H + M2M + H2M via MCP).
4. Preserves optionality to evolve into usage-based pricing on agent operations as M2M traffic scales.

## Positioning Constraints

These are non-negotiable inputs from prior product decisions:

- **Agents are first-class, not penalized.** Charging per agent contradicts the wedge. Humans are the unit because humans approve budgets.
- **Collaboration is the value moment.** Solo use is a habit-builder; the willingness-to-pay event is when collaboration begins (second human, shared workspace, team controls).
- **MCP is the editing surface.** Pricing must work for users who never open a UI — i.e., the "agent runs against my workspace" pattern is normal, not exceptional.

## Value Metric

**Per-workspace base + per-human-seat expansion**, with a path to **per-agent-operation overage** as a metered add-on once metering infrastructure exists.

Why this shape:
- Workspace = unit of "shared knowledge surface" (matches positioning).
- Human seats = unit that grows with customer success and aligns with how buyers budget.
- Agent operations = the resource that actually costs money to serve, and that scales with the M2M thesis. Reserved as a future overage lever, not a launch-day primitive.

## Tier Structure

Four tiers at launch:

### Free — $0

**For:** solo users, casual collaborators, evaluators, the agent ecosystem.

**Includes:**
- Unlimited solo workspaces.
- Connect unlimited agents (user-supplied API keys / MCP clients).
- Full read + write via MCP.
- Public read-only sharing of a workspace via link.
- **Agent operations: 1,000 / month** (placeholder — see "Open Considerations" below).

**Personal use only** — defined as a single human using the workspace for their own work (including freelancers / solo consultants). The moment a second human is invited or the workspace is shared inside an organization, Teams is required. Enforcement is honor-system at signup, hard-paywalled at the "invite second human" moment.

### Plus — $8/month ($80/year)

**For:** solo power users running heavy agent workloads who don't need collaboration features.

**Includes everything in Free, plus:**
- Truly unlimited agent operations (subject to fair-use abuse limits).
- Larger file size + per-workspace storage caps.
- Priority support.
- (Possibly later: branded public workspace, custom domain on shared links.)

**Plus is a revenue-capture tier, not a strategic tier.** Its job is to convert heavy solo users who would otherwise stay on Free. See "Open Considerations" for the kill criterion.

### Teams — $49/month flat for up to 5 humans, then $12/seat/month after

**For:** small teams (2–10 people) and growing teams up to ~50 humans.

**Includes everything in Plus, plus:**
- Shared team workspaces (multi-human collaboration).
- Org-wide directory + sharing controls.
- SSO (Google Workspace / Microsoft) — light-touch SSO at this tier; SAML/SCIM reserved for Enterprise.
- Audit log of agent + human activity (the trust/safety story; reuses existing audit infra).
- Larger storage + file-size limits than Plus.
- Encryption at rest (customer-managed keys reserved for Enterprise).
- Priority support, faster SLAs than Plus.

**Pricing rationale:**
- $49 flat covers the most common shape (2–5 person teams) with a single round number; avoids the "3 seats × $12 = $36, why upgrade from Plus" dead zone.
- $12/seat above 5 expands revenue automatically as customers grow.
- Maps to mid-market peers (Linear Standard $10, Notion Plus $10, Slack Pro $8.75) with a small premium justified by the agent-audit story.

### Enterprise — Custom (floor ~$1,500/month, annual)

**For:** larger SMB / smaller enterprise contracts. The "few smaller enterprise contracts" line in the revenue mix.

**Includes everything in Teams, plus:**
- SAML SSO + SCIM provisioning.
- Customer-managed encryption keys.
- DPA, configurable data retention, custom contract terms.
- SOC 2 attestation (when achieved).
- Higher agent-operation ceilings + usage reporting.
- Named support contact.

**Floor of $1,500/mo** keeps founder-sales effort proportional to deal size and avoids contracts that consume disproportionate calendar time.

### Annual Discount

Standard 2 months free (~17% off) for annual prepay on **Plus** and **Teams**. **Enterprise** is annual-only.

## Path-to-Target Math

One realistic blend to reach $25K MRR by month 12:

| Tier         | Customers | Avg ARPU | MRR        |
| ------------ | --------- | -------- | ---------- |
| Plus         | 400       | $8       | $3,200     |
| Teams (avg 6 seats: $49 + 1×$12) | 200 | ~$61 | $12,200 |
| Enterprise   | 4         | ~$2,500  | $10,000    |
| **Total**    |           |          | **~$25,400** |

**Riskiest line:** Enterprise. 4 customers in 12 months is achievable but requires deliberate top-of-funnel work (founder outreach, design partner program). If Enterprise underperforms, Teams must overperform (~410 Teams customers at the same ARPU) to compensate — which implies the self-serve funnel is the dominant lever to invest in.

## Future Path (D — Hybrid Usage-Based)

Once metering infrastructure exists and customer usage patterns are observable, layer **agent-operation overage** onto Teams and Enterprise:

- Each tier includes a generous monthly bucket of agent operations.
- Heavy automated usage (e.g., 24/7 bots) bills as overage above the bucket.
- Buckets sized so >90% of customers never see the overage line — overage exists to capture upside from the small fraction of customers driving the M2M growth thesis, not to nickel-and-dime everyone.

**Not in v1.** Adding metering before product-market fit would slow launch without revenue benefit. Revisit when (a) Teams has >50 paying customers and (b) at least one customer's agent-op volume is materially above bucket norms.

## Free → Paid Upgrade Triggers

The product needs honest, non-spammy upgrade prompts at moments where the user *experiences* the value of paying:

- Inviting a second human → "You're starting a team. Teams plan unlocks shared workspaces and audit." (Hard paywall — collaboration is the wedge.)
- Hitting the agent-op cap on Free → "You've used your monthly agent ops. Plus removes the cap." (Soft paywall — read-only until next month or upgrade.)
- Using Markland for work email domain detected on signup → mention Teams in onboarding (no paywall, just signal).

## Open Considerations

These were flagged during brainstorming and require ongoing attention rather than a launch-blocking decision.

### 1. Free tier agent-op bucket sizing

**The risk:** without *any* cap on agent operations on Free, a single user can run a bot writing 24/7 and consume real infrastructure cost — turning Free from a marketing expense into a variable cost line.

**Working number:** 1,000 agent operations / month. This is a placeholder, not a researched figure.

**What to refine before launch:**
- Define what counts as one "agent operation" (a single MCP write? a tool call? a request?). The definition shapes the number.
- Instrument actual usage from internal/dogfooding workspaces to ground the number in reality.
- Decide soft vs hard cap behavior: read-only freeze, write-throttling, or upgrade prompt.

**What to refine post-launch:**
- Watch for abuse patterns (single Free user driving disproportionate cost).
- Watch the Free → Plus conversion rate at the cap; if conversion is high, the cap may be too tight; if zero users hit it, the cap is irrelevant and the bucket can grow.

### 2. Plus tier kill criterion

**Plus is hypothesis-driven.** It exists to capture revenue from heavy solo users, but it's plausible that nearly everyone either stays Free (the cap is high enough) or jumps to Teams (because their usage implies collaboration is coming).

**Explicit kill criterion:** If Plus accounts for **<5% of paid revenue at month 6 post-launch**, fold its features into Free (raise the agent-op cap, raise storage) and simplify to a 3-tier ladder (Free / Teams / Enterprise).

**Why this matters:** keeping Plus alive when nobody pays for it adds pricing-page complexity (one more tier to compare), support surface, and decision friction without revenue. A 3-tier ladder is easier to explain and easier to trust.

**What to instrument from day 1** to make this evaluation possible:
- Plus MRR as % of total paid MRR (weekly).
- Free → Plus conversion rate (to distinguish "Plus is wrong" from "Plus has no top-of-funnel").
- Plus → Teams conversion rate (to confirm Plus is a stepping stone, not a dead end).

## Out of Scope (for this spec)

- Specific implementation of billing infrastructure (Stripe vs Paddle vs LemonSqueezy) — choose during implementation planning.
- Trial-vs-no-trial decision for Teams (current draft has no trial; revisit after watching self-serve conversion behavior).
- Affiliate / partner program design.
- Discount structure for non-profits, students, OSS maintainers (defer to post-launch unless a specific opportunity surfaces).
- Pricing-page copy and conversion design (handled by `copywriting` + `page-cro` skills when we get there).

## Decisions Locked In

- Value metric: **per-workspace base + per-seat expansion**, with future path to per-agent-op overage.
- Free tier: solo + unlimited agents within a monthly op cap.
- Plus tier: $8/mo, single solo upgrade tier with kill criterion.
- Teams tier: $49/mo flat (≤5 humans) + $12/seat/mo above 5.
- Enterprise tier: custom, $1,500/mo floor, annual.
- Annual discount: 2 months free on Plus + Teams.
- No charge per agent. Ever. Agents are equal editors, not line items.
