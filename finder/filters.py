"""Decide which jobs are internships, where they are, and whether they're tech or business."""
from __future__ import annotations

import re

from .sources import Job


def _words(patterns):
    # "co-op" matches "co-op", "co op", "coop"; "summer analyst" matches "Summer-Analyst" too
    alts = [r"[\s\-]*".join(re.escape(t) for t in re.split(r"[\s\-]+", p.strip()) if t)
            for p in patterns if p.strip()]
    return re.compile(r"(?<![a-z])(" + "|".join(alts) + r")(?![a-z])", re.I) if alts else None


class Filter:
    def __init__(self, cfg: dict):
        self.include = _words(cfg.get("include_title_patterns", ["intern", "internship"]))
        self.exclude = _words(cfg.get("exclude_title_patterns", []))
        self.us_only = cfg.get("us_only", True)
        self.categories = set(cfg.get("post_categories", ["tech", "business", "other"]))

    def is_internship(self, title: str, curated: bool = False) -> bool:
        if not title or not (curated or self.include.search(title)):
            return False
        return not (self.exclude and self.exclude.search(title))

    def location_ok(self, location: str) -> bool:
        return (not self.us_only) or not is_clearly_non_us(location)

    def accept(self, job: Job) -> bool:
        # The Simplify feed is already a curated internship list, so don't re-check titles.
        return (self.is_internship(job.title, curated=job.source == "simplify")
                and self.location_ok(job.location) and classify(job) in self.categories)


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

TECH = re.compile(
    r"\b(software|engineer\w*|developer|data|machine learning|ml|ai|artificial intelligence|"
    r"computer|cyber\w*|security|cloud|devops|sre|hardware|firmware|embedded|electrical|"
    r"mechanical|robotics|research scientist|quantitative developer|it|information technology|"
    r"technology|technical|systems|network\w*|web|mobile|ios|android|frontend|backend|full[\s-]?stack|"
    r"product manag\w*|product design|ux|ui|analytics engineer|database|platform|infrastructure|"
    r"semiconductor|asic|fpga|silicon|chip|automation|programmer|r&d)\b", re.I)
BUSINESS = re.compile(
    r"\b(business|finance|financial|accounting|accountant|audit|tax|banking|investment|"
    r"analyst|consult\w*|strategy|marketing|brand|sales|trading|trader|quant\w*|equity|"
    r"capital markets|wealth|asset management|private equity|venture|treasury|risk|"
    r"operations|supply chain|procurement|merchandising|economics|actuar\w*|underwrit\w*|"
    r"commercial|corporate development|m&a|summer analyst|summer associate|mba|"
    r"communications|public relations|advertising|real estate|insurance|credit|fp&a|"
    r"category manag\w*|buyer|planning|revenue|pricing|growth)\b", re.I)


def classify(job: Job) -> str:
    hint = (job.category_hint or "").lower()
    if hint:
        if "quant" in hint:
            return "business"
        return "tech"           # Simplify's other categories are all tech/product
    t = job.title
    tech, biz = bool(TECH.search(t)), bool(BUSINESS.search(t))
    if tech and biz:
        # "Data Analyst", "Technology Risk", "Software Sales"... lean on strongest words
        if re.search(r"\b(software|engineer\w*|developer|machine learning|hardware|firmware|cyber\w*)\b", t, re.I):
            return "tech"
        return "business"
    if tech:
        return "tech"
    if biz:
        return "business"
    return "other"
