"""Decide which jobs are undergrad internships, where they are, and what kind of role they are."""
from __future__ import annotations

import re
import time

from .sources import Job
from .tiers import is_tech_company


def _words(patterns):
    # "co-op" matches "co-op", "co op", "coop"; "summer analyst" matches "Summer-Analyst" too
    alts = [r"[\s\-]*".join(re.escape(t) for t in re.split(r"[\s\-]+", p.strip()) if t)
            for p in patterns if p.strip()]
    return re.compile(r"(?<![a-z])(" + "|".join(alts) + r")(?![a-z])", re.I) if alts else None


def _norm(s):
    s = re.sub(r"\(.*?\)", " ", s.lower())
    s = re.sub(r"\b(the|inc|corp|corporation|company|co|llc|plc|ltd|group|holdings)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


class Filter:
    def __init__(self, cfg: dict):
        self.include = _words(cfg.get("include_title_patterns", ["intern", "internship"]))
        self.exclude = _words(cfg.get("exclude_title_patterns", []))
        self.us_only = cfg.get("us_only", True)
        self.categories = set(cfg.get("post_categories", list(LABELS)))
        self.eng_companies = [_norm(c) for c in cfg.get("engineering_companies", []) if c.strip()]
        self.off_season = bool(cfg.get("include_off_season", False))
        self.grad_years = set(int(y) for y in cfg.get("target_grad_years", []) or [])
        self.tech_only_for = set(cfg.get("tech_companies_only_for", []) or [])
        # Summer internships for a summer that's already over are stale.
        t = time.gmtime()
        self.min_summer_year = t.tm_year + (1 if t.tm_mon >= 9 else 0)

    # ---- cheap checks on the listing itself (title, location, company, Simplify degree list)
    def is_internship(self, title: str, curated: bool = False) -> bool:
        if not title or not (curated or self.include.search(title)):
            return False
        return not (self.exclude and self.exclude.search(title))

    def location_ok(self, location: str) -> bool:
        return (not self.us_only) or not is_clearly_non_us(location)

    def engineering_ok(self, company: str) -> bool:
        c = _norm(company)
        return any(c == e or (len(e) >= 5 and c.startswith(e)) for e in self.eng_companies)

    def accept(self, job: Job) -> bool:
        # The Simplify feed is already a curated internship list, so don't re-check titles.
        if not self.is_internship(job.title, curated=job.source == "simplify"):
            return False
        if not self.location_ok(job.location):
            return False
        if job.degrees and not any(d.lower().startswith(("bachelor", "associate")) for d in job.degrees):
            return False                      # Simplify says Master's / PhD / MBA only
        cat = classify(job)
        if cat not in self.categories:
            return False
        if cat == "engineering" and not self.engineering_ok(job.company):
            return False
        if cat in self.tech_only_for and not is_tech_company(job):
            return False
        return True

    # ---- checks that need the full description (run only on jobs about to be posted)
    def reject_reason(self, info: dict) -> str | None:
        if info.get("grad_only"):
            return "grad-level (MBA/Master's/PhD)"
        season, year = info.get("season"), info.get("season_year")
        if season == "summer" and year and year < self.min_summer_year:
            return f"past summer ({year})"
        if not self.off_season:
            if season and season != "summer":
                return f"off-season ({season})"
            if not season and info.get("coop"):
                return "co-op without summer dates"
        ys = info.get("grad_years") or []
        if self.grad_years and ys and not (set(ys) & self.grad_years):
            return f"grad year {ys} outside target"
        return None


# ------------------------------------------------------------------ location

STRONG_US = re.compile(
    r"\b(united states|usa|u\.s\.a?\.?|new york|san francisco|seattle|chicago|boston|austin|"
    r"atlanta|dallas|houston|denver|los angeles|charlotte|philadelphia|pittsburgh|miami|phoenix|"
    r"san jose|san diego|minneapolis|detroit|columbus|raleigh|nashville|salt lake|st\.? louis|tampa)\b",
    re.I)
NON_US = re.compile(
    r"\b(canada|ontario|toronto|vancouver|montreal|quebec|alberta|calgary|ottawa|british columbia|"
    r"mexico|brazil|argentina|chile|colombia|peru|"
    r"united kingdom|uk|england|london|scotland|ireland|dublin|france|paris|germany|berlin|munich|"
    r"netherlands|amsterdam|belgium|spain|madrid|barcelona|portugal|lisbon|italy|milan|switzerland|"
    r"zurich|geneva|austria|vienna|poland|warsaw|krakow|czech|prague|romania|bucharest|hungary|"
    r"sweden|stockholm|denmark|copenhagen|norway|finland|greece|turkey|istanbul|israel|tel aviv|"
    r"uae|dubai|saudi|qatar|egypt|south africa|nigeria|kenya|"
    r"india|bangalore|bengaluru|hyderabad|mumbai|pune|chennai|delhi|gurgaon|gurugram|noida|"
    r"china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|japan|tokyo|korea|seoul|"
    r"singapore|malaysia|kuala lumpur|philippines|manila|vietnam|thailand|bangkok|indonesia|jakarta|"
    r"australia|sydney|melbourne|new zealand|auckland)\b", re.I)


def is_clearly_non_us(location: str) -> bool:
    if not location:
        return False
    # Check each listed location; keep the job if any of them could be in the US.
    parts = [p for p in re.split(r";|\n|\|", location) if p.strip()]
    for p in parts:
        if STRONG_US.search(p):
            return False          # definitely US
        if not NON_US.search(p):
            return False          # US state code, "Remote", or ambiguous: keep it
    return True                   # every location names another country


# ------------------------------------------------------------------ category
# Checked in this order; the first match wins.

LABELS = {
    "consulting": "🧠 Consulting & Strategy",
    "product": "🧭 Product",
    "finance": "📈 Finance",
    "marketing": "📣 Marketing",
    "business": "💼 Business & Ops",
    "data_it": "📊 Data, Analytics & IT",
    "engineering": "💻 Engineering",
    "other": "🧩 Other",
}

_R = lambda p: re.compile(p, re.I)  # noqa: E731
RULES = [
    ("engineering", _R(r"\b(software|swe|developer|machine learning|deep learning|\bml\b|\bai\b|"
                       r"artificial intelligence|data scien\w*|data engineer\w*|research (?:scientist|engineer)|"
                       r"hardware|firmware|embedded|electrical|mechanical|robotics|silicon|asic|fpga|"
                       r"frontend|front-end|backend|back-end|full[\s-]?stack|ios|android|devops|sre|"
                       r"site reliability|computer vision|compiler|kernel|gpu|engineer|engineers|engineering|"
                       r"technical artist|game design\w*)\b"), True),
    ("consulting", _R(r"\b(consult\w*|strateg\w*|corporate development|transformation|advisory|"
                      r"management associate|chief of staff|ventures?)\b"), False),
    ("marketing", _R(r"\b(marketing|brand|communications|public relations|\bpr\b|advertis\w*|social media|"
                     r"content|growth|creative|media|partnerships)\b"), False),
    ("product", _R(r"\b(product manag\w*|product owner|apm|product analyst|product strategy|"
                   r"product operations|product intern|product development|product)\b"), False),
    ("finance", _R(r"\b(financ\w*|accounting|accountant|audit\w*|tax|banking|banker|investment\w*|"
                   r"capital markets|equity|equities|trading|trader|quant\w*|wealth|asset management|"
                   r"private equity|venture capital|treasury|risk|credit|actuar\w*|underwrit\w*|fp&a|"
                   r"summer analyst|economic\w*|markets|fixed income|m&a|mergers|restructuring|"
                   r"real estate|insurance|valuation)\b"), False),
    ("data_it", _R(r"\b(data analy\w*|business analy\w*|analytics|business intelligence|\bbi\b|"
                   r"\bit\b|information technology|technology analyst|cyber\w*|solutions|sales engineer|"
                   r"technical|technology|systems analyst|data)\b"), False),
    ("business", _R(r"\b(business|operations|supply chain|procurement|sourcing|logistics|sales|"
                    r"merchandis\w*|buyer|category|commercial|account management|customer success|"
                    r"planning|program|project|analyst|people|human resources|\bhr\b|talent|"
                    r"legal|compliance|policy|government|sustainability|esg|retail|hospitality)\b"), False),
]
# Role words that pull a title out of "engineering" even if it mentions an engineering word,
# e.g. "Product Manager Intern - AI Platform" or "Technology Consulting Intern".
_BUSINESS_OVERRIDE = _R(r"\b(product manag\w*|consult\w*|strateg\w*|business analy\w*|"
                        r"financial engineer\w*|sales|marketing|supply chain|industrial engineer\w*)\b")


def classify(job: Job) -> str:
    t = job.title
    for cat, rx, needs_check in RULES:
        if rx.search(t):
            if needs_check and _BUSINESS_OVERRIDE.search(t):
                continue
            return cat
    hint = (job.category_hint or "").lower()
    if "product" in hint:
        return "product"
    if "quant" in hint:
        return "finance"
    if hint:                       # Simplify's Software / AI/ML/Data / Hardware
        return "engineering"
    return "other"


def is_tech(cat: str) -> bool:
    """For Slack routing: which categories go to the tech channel if you have one."""
    return cat in ("engineering", "data_it")
