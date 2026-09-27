"""Synthetic enterprise SaaS dataset generator.

Produces four realistic, deliberately *messy* tables for a fictional B2B
revenue-operations platform ("Nimbus"), mirroring what you would export from a
real enterprise stack:

    features.csv            Product catalog / feature list (DB export)
    usage_monthly.csv       Monthly active users per feature (product analytics)
    engineering_logs.csv    Maintenance hours, bug tickets, commits (Jira / GitHub)
    feedback.csv            Unstructured support tickets & reviews (Zendesk, G2, NPS)

Each feature is secretly assigned a strategic *archetype* (star, cash cow,
complexity trap, ...) that drives its usage curve, cost profile and feedback
mix. The archetype is NOT written to the CSVs - the analytics pipeline has to
rediscover it from the raw signals. Ground-truth labels are returned
separately (``SyntheticDataset.truth``) so tests can measure accuracy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIES = ["Core Utility", "UX Friction", "Performance Issue", "Feature Bloat Indicator"]

TIER_ELIGIBLE_SEATS = {"All": 48_000, "Pro+": 29_000, "Enterprise": 11_500}
TOTAL_ENTERPRISE_CLIENTS = 180

# fmt: off
# (feature_id, name, module, tier, archetype, description, overrides)
FEATURE_CATALOG: list[tuple] = [
    ("F001", "Contact Management", "Core CRM", "All", "cash_cow", "Central contact & account records with custom fields", {}),
    ("F002", "Deal Pipeline", "Core CRM", "All", "cash_cow", "Kanban pipeline for tracking opportunities by stage", {"rev": (45e5, 60e5)}),
    ("F003", "Email Sync", "Core CRM", "All", "heavyweight", "Two-way Gmail / Outlook email and thread sync", {}),
    ("F004", "Calendar Integration", "Core CRM", "All", "cash_cow", "Meeting scheduling and calendar sync", {}),
    ("F005", "Lead Scoring", "Core CRM", "Pro+", "star", "Rules + ML based lead prioritisation", {}),
    ("F006", "Activity Timeline", "Core CRM", "All", "cash_cow", "Chronological log of every customer touchpoint", {}),
    ("F007", "Custom Report Builder", "Analytics", "Pro+", "heavyweight", "Drag-and-drop report designer with joins", {}),
    ("F008", "Executive Dashboards", "Analytics", "Pro+", "star", "KPI dashboards for sales leadership", {}),
    ("F009", "Revenue Forecasting", "Analytics", "Enterprise", "star", "Quota and pipeline based revenue forecasts", {}),
    ("F010", "Legacy PDF Report Exporter", "Analytics", "All", "trap", "Pixel-perfect PDF export engine (v1 renderer)", {}),
    ("F011", "Pivot Table Explorer", "Analytics", "Pro+", "trap", "Spreadsheet-style pivot analysis", {}),
    ("F012", "Cohort Analysis", "Analytics", "Enterprise", "question_mark", "Retention cohorts for customer accounts", {}),
    ("F013", "AI Email Assistant", "AI", "Pro+", "question_mark", "LLM drafted follow-up emails", {"rev": (5e5, 9e5)}),
    ("F014", "Conversation Intelligence", "AI", "Enterprise", "question_mark", "Call transcription and deal-risk signals", {}),
    ("F015", "Predictive Churn Alerts", "AI", "Enterprise", "question_mark", "Early warning for at-risk accounts", {"maint": (60, 110)}),
    ("F016", "Chatbot Builder v1", "AI", "Pro+", "trap", "Rule-based website chatbot designer", {}),
    ("F017", "Salesforce Bi-directional Sync", "Integrations", "Enterprise", "heavyweight", "Real-time object sync with Salesforce", {}),
    ("F018", "Slack Notifications", "Integrations", "All", "cash_cow", "Deal and task alerts in Slack channels", {"rev": (6e5, 12e5)}),
    ("F019", "Zapier Connector", "Integrations", "Pro+", "niche", "No-code automation triggers", {}),
    ("F020", "Legacy SOAP API", "Integrations", "Enterprise", "trap", "XML/SOAP API kept for pre-2019 integrations", {"ent": (55, 85)}),
    ("F021", "On-prem LDAP Connector", "Integrations", "Enterprise", "trap", "Directory sync for self-hosted identity servers", {"ent": (40, 70)}),
    ("F022", "Webhooks", "Integrations", "Pro+", "niche", "Outbound event webhooks", {}),
    ("F023", "Team Inbox", "Collaboration", "All", "star", "Shared inbox for customer-facing teams", {}),
    ("F024", "Internal Wiki", "Collaboration", "All", "trap", "Knowledge base pages inside the CRM", {}),
    ("F025", "Video Meeting Recorder", "Collaboration", "Pro+", "declining", "Native meeting recording and playback", {}),
    ("F026", "Shared Notes", "Collaboration", "All", "niche", "Collaborative notes on accounts", {}),
    ("F027", "Gamification Leaderboards", "Collaboration", "Pro+", "trap", "Sales contests, badges and leaderboards", {}),
    ("F028", "SSO / SAML", "Admin & Security", "Enterprise", "cash_cow", "Single sign-on via SAML 2.0 and OIDC", {"ent": (160, 178)}),
    ("F029", "Role-based Permissions", "Admin & Security", "All", "heavyweight", "Granular roles, profiles and field-level security", {}),
    ("F030", "Audit Logs", "Admin & Security", "Enterprise", "cash_cow", "Immutable log of admin and data changes", {}),
    ("F031", "White-label Branding", "Admin & Security", "Enterprise", "niche", "Custom domains, logos and themes", {}),
    ("F032", "Data Residency Controls", "Admin & Security", "Enterprise", "star", "Region-pinned data storage (IN / EU / US)", {}),
    ("F033", "Sandbox Environments", "Admin & Security", "Enterprise", "question_mark", "Isolated test orgs for admins", {}),
    ("F034", "Email Campaigns", "Marketing", "Pro+", "cash_cow", "Bulk email campaigns with templates", {}),
    ("F035", "Landing Page Builder", "Marketing", "Pro+", "declining", "Drag-and-drop landing pages", {}),
    ("F036", "Social Media Scheduler", "Marketing", "Pro+", "trap", "Schedule posts to LinkedIn, X and Facebook", {}),
    ("F037", "SMS Campaigns", "Marketing", "Pro+", "niche", "Bulk SMS with DLT template support", {}),
    ("F038", "Web Forms", "Marketing", "All", "cash_cow", "Embeddable lead capture forms", {}),
    ("F039", "Mobile App", "Mobile", "All", "heavyweight", "Native iOS and Android CRM app", {}),
    ("F040", "Offline Mode", "Mobile", "All", "trap", "Local-first offline editing on mobile", {}),
    ("F041", "Business Card Scanner", "Mobile", "All", "niche", "OCR contact capture from business cards", {}),
    ("F042", "Territory Management", "Core CRM", "Enterprise", "declining", "Geographic and account-based territory rules", {}),
]
# fmt: on

# Parameter ranges per archetype. Monetary values in INR; `plateau` is the
# share of eligible seats actively using the feature at maturity.
ARCHETYPES: dict[str, dict] = {
    "star":          dict(plateau=(0.50, 0.78), age=(10, 22), shape="growth",  rev=(16e5, 38e5), maint=(120, 230), bugs=(4, 10), ent=(60, 130), dev=(80e5, 220e5), mix=[.58, .17, .19, .06]),
    "cash_cow":      dict(plateau=(0.60, 0.90), age=(36, 78), shape="mature",  rev=(18e5, 52e5), maint=(25, 80),   bugs=(1, 5),  ent=(110, 170), dev=(40e5, 150e5), mix=[.64, .18, .13, .05]),
    "heavyweight":   dict(plateau=(0.50, 0.85), age=(30, 78), shape="mature",  rev=(24e5, 65e5), maint=(330, 620), bugs=(18, 40), ent=(100, 170), dev=(150e5, 320e5), mix=[.36, .24, .35, .05]),
    "question_mark": dict(plateau=(0.30, 0.60), age=(3, 9),   shape="ramp",    rev=(1e5, 6e5),   maint=(140, 300), bugs=(8, 20), ent=(8, 40),    dev=(60e5, 180e5), mix=[.36, .34, .20, .10]),
    "trap":          dict(plateau=(0.05, 0.20), age=(30, 84), shape="fading",  rev=(0, 2e5),     maint=(190, 430), bugs=(14, 34), ent=(3, 25),   dev=(50e5, 200e5), mix=[.08, .24, .30, .38]),
    "niche":         dict(plateau=(0.06, 0.22), age=(18, 60), shape="mature",  rev=(0.5e5, 3e5), maint=(15, 55),   bugs=(1, 4),  ent=(5, 40),    dev=(10e5, 50e5),  mix=[.46, .20, .10, .24]),
    "declining":     dict(plateau=(0.35, 0.60), age=(40, 84), shape="decline", rev=(3e5, 10e5),  maint=(90, 200),  bugs=(6, 14), ent=(20, 60),   dev=(60e5, 160e5), mix=[.20, .25, .25, .30]),
}

# --------------------------------------------------------------------------
# Feedback text templates: category -> sub-theme -> templates
# --------------------------------------------------------------------------
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "Performance Issue": {
        "Slow load times": [
            "{f} takes forever to load, sometimes over 30 seconds.",
            "Loading {f} is painfully slow for {team}.",
            "The {f} page keeps spinning, load times have gotten much worse since the last release.",
            "Why is {f} so slow? It lags every single time we open it.",
            "{f} is sluggish during peak hours, pages take ages to render.",
        ],
        "Crashes & errors": [
            "{f} crashes whenever we {action}.",
            "Getting an error 500 in {f} again when we {action}.",
            "{f} froze and we lost our work. Third time this week.",
            "Unexpected error when saving in {f}, we have to refresh constantly.",
            "The app crashes when {team} try to {action} in {f}.",
        ],
        "Sync failures": [
            "{f} failed to sync overnight and the data is out of date.",
            "Sync errors in {f}, records are missing or duplicated.",
            "{f} stopped syncing for {team} after the update.",
            "Data from {f} is not syncing reliably, we see stale records every morning.",
        ],
        "Timeouts on large data": [
            "{f} times out on large datasets.",
            "Requests to {f} time out when we have more than {n} records.",
            "Export from {f} timed out after 10 minutes.",
            "{f} hits a timeout whenever {team} load a big account.",
        ],
    },
    "UX Friction": {
        "Confusing navigation": [
            "Can't figure out where to find the settings in {f}.",
            "{f} is confusing, the navigation makes no sense to {team}.",
            "It's unintuitive how {f} is organised, we keep getting lost.",
            "Hard to find anything in {f}, the menus are confusing.",
        ],
        "Too many clicks": [
            "It takes way too many clicks to do anything in {f}.",
            "Simple tasks in {f} need six or seven steps, very clunky workflow.",
            "The {f} workflow is clunky, why can't we do this in one step?",
            "Too many steps and clicks in {f} just to {action}.",
        ],
        "Poor onboarding & docs": [
            "No documentation for {f}, onboarding new reps is hard.",
            "{team} needed training just to understand {f}, the docs are outdated.",
            "The help articles for {f} don't match the current UI.",
            "Onboarding to {f} is painful, the tutorial skips important steps.",
        ],
        "Broken mobile layout": [
            "The {f} layout is broken on smaller screens, buttons overlap.",
            "Hard to read {f} on mobile, text is cut off.",
            "{f} is not responsive, the layout breaks on tablets.",
        ],
    },
    "Feature Bloat Indicator": {
        "Never used": [
            "Honestly nobody on our team uses {f}.",
            "We have never used {f} in two years, not sure what it is for.",
            "{f} seems irrelevant to how we work, nobody uses it.",
            "I don't know anyone who actually uses {f}.",
        ],
        "Clutters the interface": [
            "{f} clutters the sidebar, can we hide it?",
            "Too much noise, {f} adds clutter to an already busy screen.",
            "The menu is bloated with things like {f}.",
            "{f} is just clutter in the navigation for {team}.",
        ],
        "Redundant with other tools": [
            "{f} duplicates what {other} already does.",
            "Why do we have {f} when {other} does the same thing better?",
            "{f} overlaps with our existing tools, it's redundant for us.",
            "We use {other} instead, so {f} is redundant.",
        ],
        "Requests to disable/remove": [
            "Please let admins disable {f} entirely.",
            "How do we turn off {f}? Our users find it distracting.",
            "Can you remove {f} from our plan? We're paying for features we don't use.",
            "Is there a way to switch off {f} for {team}? It's unnecessary.",
        ],
    },
    "Core Utility": {
        "Saves time": [
            "{f} saves {team} hours every week.",
            "Love {f}, it cut our reporting time in half.",
            "{f} is a huge time saver for us.",
            "Thanks to {f}, {team} spend far less time on manual work.",
        ],
        "Mission critical": [
            "{f} is essential to our daily workflow.",
            "We rely on {f} every day, can't imagine working without it.",
            "{f} is critical for {team}, it's the main reason we renewed.",
            "{f} is core to how we run our pipeline reviews.",
        ],
        "Praise & reliability": [
            "{f} just works, very reliable.",
            "Great job on {f}, it's the best part of the product.",
            "{f} is fantastic and really valuable for our business.",
            "Really happy with {f}, it works well for {team}.",
        ],
        "Expansion requests": [
            "Would love {f} to also support {ext}.",
            "Please extend {f} with {ext}, we'd use it even more.",
            "{f} is great, adding {ext} would make it perfect.",
            "We use {f} heavily; could you add {ext}?",
        ],
    },
}

GENERIC_FILLERS = {
    "team": ["our sales reps", "the finance team", "our admins", "customer success", "the marketing team", "our managers", "RevOps", "the inside sales team"],
    "action": ["export a report", "add a filter", "save changes", "upload a file", "switch accounts", "open a large account", "bulk edit records"],
    "ext": ["custom fields", "bulk actions", "API access", "multi-currency", "scheduled exports", "role-level visibility", "Hindi language support"],
    "n": ["10,000", "50k", "100,000", "a million", "25k"],
    "other_generic": ["Excel", "our BI tool", "Google Sheets", "Notion", "the main dashboard", "HubSpot", "Confluence"],
}
PREFIXES = ["", "", "", "", "Hi team, ", "Hello, ", "FYI: ", "Quick feedback: ", "Honestly, ", "Ticket from admin: "]
SUFFIXES = ["", "", "", " Thanks!", " Please advise.", " This is blocking our team.", " Any update on this?", " Rated 3/5.", " Raised by our account manager."]
SOURCES = ["Zendesk", "Zendesk", "Jira Service Desk", "G2 Review", "NPS Survey", "Sales Call Notes", "Community Forum"]
UNATTRIBUTED_GENERIC = [
    "The whole app feels slow this week.",
    "Too many features we never use, the product feels bloated.",
    "Navigation is confusing overall, hard to find things.",
    "Overall a solid product, it saves us a lot of time.",
    "We keep getting random errors across the platform.",
]


@dataclass
class SyntheticDataset:
    features: pd.DataFrame
    usage: pd.DataFrame
    engineering: pd.DataFrame
    feedback: pd.DataFrame
    truth: dict = field(default_factory=dict)

    def save(self, out_dir: str | Path) -> Path:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.features.to_csv(out / "features.csv", index=False)
        self.usage.to_csv(out / "usage_monthly.csv", index=False)
        self.engineering.to_csv(out / "engineering_logs.csv", index=False)
        self.feedback.to_csv(out / "feedback.csv", index=False)
        return out


def _month_starts(as_of: date, n_months: int) -> list[date]:
    months = []
    y, m = as_of.year, as_of.month
    for _ in range(n_months):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return months[::-1]


def _default_as_of() -> date:
    """Last fully completed calendar month."""
    today = date.today()
    y, m = today.year, today.month - 1
    if m == 0:
        y, m = y - 1, 12
    return date(y, m, 1)


def _curve(shape: str, age_now: int, rng: np.random.Generator) -> callable:
    """Return f(age_months) -> share of plateau adoption (0..~1)."""
    def logistic(a, mid, s):
        return 1.0 / (1.0 + math.exp(-(a - mid) / s))

    if shape == "growth":
        mid, s = age_now - rng.uniform(0, 3), rng.uniform(2.5, 3.5)
        return lambda a: logistic(a, mid, s)
    if shape == "ramp":
        mid, s = age_now + rng.uniform(0.5, 3), rng.uniform(1.4, 2.2)
        return lambda a: logistic(a, mid, s)
    if shape == "mature":
        mid, s = rng.uniform(4, 8), rng.uniform(1.5, 2.5)
        drift = rng.uniform(-0.003, 0.004)
        return lambda a: logistic(a, mid, s) * (1 + drift * max(0, a - 24))
    if shape == "decline":
        mid, s = rng.uniform(4, 8), rng.uniform(1.5, 2.5)
        peak, tau = age_now - rng.uniform(12, 20), rng.uniform(14, 22)
        return lambda a: logistic(a, mid, s) * (math.exp(-(a - peak) / tau) if a > peak else 1.0)
    if shape == "fading":
        mid, s = rng.uniform(4, 8), rng.uniform(1.5, 2.5)
        peak, tau = age_now - rng.uniform(8, 22), rng.uniform(28, 60)
        return lambda a: logistic(a, mid, s) * (math.exp(-(a - peak) / tau) if a > peak else 1.0)
    raise ValueError(shape)


def _typo(text: str, rng: np.random.Generator) -> str:
    words = text.split(" ")
    idx = int(rng.integers(0, len(words)))
    w = words[idx]
    if len(w) > 4:
        i = int(rng.integers(1, len(w) - 2))
        words[idx] = w[:i] + w[i + 1] + w[i] + w[i + 2:]
    return " ".join(words)


def generate(
    seed: int = 42,
    as_of: date | None = None,
    n_months: int = 24,
    feedback_months: int = 12,
    feedback_scale: float = 1.0,
    unattributed_rate: float = 0.12,
) -> SyntheticDataset:
    """Generate the full synthetic dataset. Deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    as_of = as_of or _default_as_of()
    months = _month_starts(as_of, n_months)

    feat_rows, usage_rows, eng_rows, fb_rows = [], [], [], []
    truth_archetype: dict[str, str] = {}
    truth_category: dict[str, str] = {}
    truth_feature: dict[str, str] = {}
    truth_theme: dict[str, str] = {}
    names_by_module: dict[str, list[str]] = {}
    for fid, name, module, *_ in FEATURE_CATALOG:
        names_by_module.setdefault(module, []).append(name)

    ticket_no = 0
    for fid, name, module, tier, arch, desc, overrides in FEATURE_CATALOG:
        p = {**ARCHETYPES[arch], **overrides}
        u = lambda key: float(rng.uniform(*p[key]))  # noqa: E731
        truth_archetype[fid] = arch

        age_now = int(rng.integers(p["age"][0], p["age"][1] + 1))
        release = months[-1]
        y, m = release.year, release.month - age_now
        while m <= 0:
            y, m = y - 1, m + 12
        release = date(y, m, int(rng.integers(1, 28)))

        eligible = TIER_ELIGIBLE_SEATS[tier]
        plateau = u("plateau")
        curve = _curve(p["shape"], age_now, rng)
        maint_base, bug_base = u("maint"), u("bugs")
        seasonal_phase = rng.uniform(0, 2 * math.pi)

        active_series = []
        for i, mth in enumerate(months):
            age = age_now - (n_months - 1 - i)
            if age < 0:
                continue
            season = 1 + 0.03 * math.sin(2 * math.pi * mth.month / 12 + seasonal_phase)
            share = max(0.0, curve(age)) * plateau * season * rng.normal(1, 0.03)
            active = int(max(0, round(eligible * min(share, 0.98))))
            active_series.append(active)
            usage_rows.append({"feature_id": fid, "month": mth.isoformat(), "active_users": active})

            # Young features burn extra hours while stabilising.
            youth = 1.0 + 0.6 * math.exp(-age / 4)
            hours = max(4.0, maint_base * youth * rng.normal(1, 0.12))
            bugs = int(rng.poisson(bug_base * youth))
            eng_rows.append({
                "feature_id": fid,
                "month": mth.isoformat(),
                "maintenance_hours": round(hours, 1),
                "bug_tickets": bugs,
                "commits": int(rng.poisson(hours / 5.5)),
                "incidents": int(rng.poisson(bug_base / 12)),
            })

        feat_rows.append({
            "feature_id": fid,
            "feature_name": name,
            "module": module,
            "tier": tier,
            "description": desc,
            "release_date": release.isoformat(),
            "development_cost_inr": int(round(u("dev"), -4)),
            "monthly_revenue_inr": int(round(u("rev"), -3)),
            "enterprise_clients": int(round(u("ent"))),
            "eligible_users": eligible,
            "owner_team": f"{module} Squad",
        })

        # ---------------- feedback tickets ----------------
        active_now = active_series[-1] if active_series else 0
        fb_window = min(feedback_months, age_now + 1)
        n_tickets = int(np.clip(0.35 * math.sqrt(active_now + 50) * (0.6 + bug_base / 20) * feedback_scale
                                * fb_window / feedback_months, 6, 130))
        others = [n for n in names_by_module[module] if n != name] + GENERIC_FILLERS["other_generic"]
        for _ in range(n_tickets):
            cat = CATEGORIES[int(rng.choice(4, p=np.array(p["mix"]) / sum(p["mix"])))]
            theme = list(TEMPLATES[cat])[int(rng.integers(0, len(TEMPLATES[cat])))]
            tpl = TEMPLATES[cat][theme][int(rng.integers(0, len(TEMPLATES[cat][theme])))]
            text = tpl.format(
                f=name,
                team=rng.choice(GENERIC_FILLERS["team"]),
                action=rng.choice(GENERIC_FILLERS["action"]),
                ext=rng.choice(GENERIC_FILLERS["ext"]),
                n=rng.choice(GENERIC_FILLERS["n"]),
                other=rng.choice(others),
            )
            prefix = str(rng.choice(PREFIXES))
            if prefix and not text.startswith((name, "I ")):
                text = text[0].lower() + text[1:]
            text = prefix + text + str(rng.choice(SUFFIXES))
            if rng.random() < 0.08:
                text = text.lower()
            if rng.random() < 0.06:
                text = _typo(text, rng)

            attributed = fid
            if rng.random() < unattributed_rate:
                attributed = ""
                if rng.random() < 0.12:
                    text = str(rng.choice(UNATTRIBUTED_GENERIC))

            days_back = int(rng.integers(0, fb_window * 30))
            created = pd.Timestamp(months[-1]) + pd.offsets.MonthEnd(0) - pd.Timedelta(days=days_back)
            ticket_no += 1
            tid = f"T{ticket_no:05d}"
            truth_category[tid] = cat
            truth_feature[tid] = fid
            truth_theme[tid] = theme
            fb_rows.append({
                "ticket_id": tid,
                "feature_id": attributed,
                "source": str(rng.choice(SOURCES)),
                "created_at": created.date().isoformat(),
                "customer_tier": str(rng.choice(["SMB", "Mid-Market", "Enterprise"], p=[0.35, 0.4, 0.25])),
                "text": text.strip(),
            })

    feedback = pd.DataFrame(fb_rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return SyntheticDataset(
        features=pd.DataFrame(feat_rows),
        usage=pd.DataFrame(usage_rows),
        engineering=pd.DataFrame(eng_rows),
        feedback=feedback,
        truth={"archetype": truth_archetype, "category": truth_category, "feature": truth_feature,
               "theme": truth_theme},
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    ds = generate()
    out = ds.save(sys.argv[1] if len(sys.argv) > 1 else "data/sample")
    print(f"Wrote {len(ds.features)} features, {len(ds.feedback)} tickets to {out}")
