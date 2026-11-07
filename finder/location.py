"""Is a job in the US? Returns "us", "non_us" or "unknown".

A job is only posted when it's confirmed US. "unknown" locations (blank, "Remote",
"2 Locations"...) get a second look at the job description before posting.
"""
from __future__ import annotations

import re

_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": None,  # "Georgia" is also a country
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland", "MA": "massachusetts",
    "MI": "michigan", "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana",
    "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico",
    "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
    "DC": "district of columbia", "PR": "puerto rico",
}
_US_CITIES = ("new york city|nyc|manhattan|brooklyn|san francisco|bay area|silicon valley|seattle|chicago|boston|"
              "austin|atlanta|dallas|fort worth|houston|denver|los angeles|charlotte|philadelphia|pittsburgh|"
              "miami|phoenix|san jose|san diego|minneapolis|detroit|columbus|raleigh|durham|nashville|"
              "salt lake city|st\\.? louis|tampa|orlando|baltimore|cleveland|cincinnati|indianapolis|"
              "kansas city|milwaukee|portland|sacramento|palo alto|mountain view|menlo park|sunnyvale|"
              "santa clara|cupertino|redmond|bellevue|cambridge, ma|arlington, va|mclean|reston|"
              "jersey city|hoboken|stamford|greenwich|plano|irving|richmond|omaha|bentonville|"
              "san antonio|las vegas|boise|albuquerque|new orleans|louisville|memphis|oklahoma city|"
              "tulsa|des moines|madison|ann arbor|irvine|santa monica|burbank|oakland|berkeley|"
              "washington,? d\\.?c\\.?|research triangle")
STRONG_US = re.compile(
    r"\b(united states(?: of america)?|u\.s\.a?\.?|usa|nationwide \(us\)|"
    + "|".join(n for n in _STATES.values() if n) + "|" + _US_CITIES + r")\b", re.I)
US_TOKEN = re.compile(r"(?<![A-Za-z])(US|USA|SF|NYC|DC|DMV)(?![A-Za-z])")   # case-sensitive
STATE_CODE = re.compile(r"(?:,\s*|\bUS[-\s,]+|\(|^|\s-\s)(" + "|".join(_STATES) + r")(?=$|[\s,)\-;/])")

_COUNTRIES = (
    "afghanistan|albania|algeria|andorra|angola|antigua|argentina|armenia|australia|austria|azerbaijan|"
    "bahamas|bahrain|bangladesh|barbados|belarus|belgium|belize|benin|bhutan|bolivia|bosnia|botswana|"
    "brazil|brunei|bulgaria|burkina faso|burundi|cambodia|cameroon|canada|cape verde|chad|chile|china|"
    "colombia|comoros|congo|costa rica|croatia|cuba|cyprus|czech republic|czechia|denmark|djibouti|"
    "dominican republic|ecuador|egypt|el salvador|equatorial guinea|eritrea|estonia|eswatini|ethiopia|"
    "fiji|finland|france|gabon|gambia|germany|ghana|greece|grenada|guatemala|guinea|guyana|haiti|"
    "honduras|hong kong|hungary|iceland|india|indonesia|iran|iraq|ireland|israel|italy|ivory coast|"
    "jamaica|japan|jordan|kazakhstan|kenya|kosovo|kuwait|kyrgyzstan|laos|latvia|lebanon|lesotho|"
    "liberia|libya|liechtenstein|lithuania|luxembourg|macau|madagascar|malawi|malaysia|maldives|mali|"
    "malta|mauritania|mauritius|(?<!new )mexico|moldova|monaco|mongolia|montenegro|morocco|mozambique|"
    "myanmar|namibia|nepal|netherlands|new zealand|nicaragua|niger|nigeria|north macedonia|norway|oman|"
    "pakistan|palestine|panama|papua new guinea|paraguay|peru|philippines|poland|portugal|qatar|"
    "romania|russia|rwanda|saudi arabia|saudi|senegal|serbia|seychelles|sierra leone|singapore|slovakia|"
    "slovenia|somalia|south africa|south korea|korea|spain|sri lanka|sudan|suriname|sweden|switzerland|"
    "syria|taiwan|tajikistan|tanzania|thailand|togo|trinidad|tunisia|turkey|türkiye|turkmenistan|uganda|"
    "ukraine|united arab emirates|uae|united kingdom|uk|england|scotland|wales|northern ireland|"
    "uruguay|uzbekistan|venezuela|vietnam|viet nam|yemen|zambia|zimbabwe|emea|apac|latam|europe|asia")
_FOREIGN_CITIES = (
    "toronto|vancouver|montreal|montréal|calgary|ottawa|edmonton|waterloo|mississauga|winnipeg|halifax|"
    "ontario|quebec|québec|british columbia|alberta|london|manchester|edinburgh|glasgow|belfast|dublin|"
    "paris|berlin|munich|frankfurt|hamburg|amsterdam|rotterdam|brussels|madrid|barcelona|lisbon|porto|"
    "milan|rome|zurich|zürich|geneva|vienna|warsaw|krakow|kraków|wroclaw|prague|bucharest|budapest|"
    "stockholm|copenhagen|oslo|helsinki|athens|istanbul|tel aviv|haifa|dubai|abu dhabi|riyadh|doha|"
    "cairo|lagos|nairobi|johannesburg|cape town|bangalore|bengaluru|hyderabad|mumbai|pune|chennai|"
    "delhi|new delhi|gurgaon|gurugram|noida|kolkata|ahmedabad|beijing|shanghai|shenzhen|guangzhou|"
    "hangzhou|chengdu|taipei|hsinchu|tokyo|osaka|seoul|singapore|kuala lumpur|manila|ho chi minh|hanoi|"
    "bangkok|jakarta|sydney|melbourne|brisbane|perth|auckland|são paulo|sao paulo|rio de janeiro|"
    "buenos aires|santiago|bogotá|bogota|lima|mexico city|guadalajara|monterrey|baku|tbilisi|yerevan|"
    "almaty|tashkent|kyiv|kiev|minsk|moscow|riga|vilnius|tallinn|sofia|belgrade|zagreb|ljubljana|"
    "bratislava|luxembourg city|reykjavik|karachi|lahore|dhaka|colombo|kathmandu")
COUNTRY = re.compile(r"\b(" + _COUNTRIES + r")\b", re.I)
FOREIGN_CITY = re.compile(r"\b(" + _FOREIGN_CITIES + r")\b", re.I)
CA_PROVINCE = re.compile(r"(?:,\s*|\(|-)(ON|QC|BC|AB|MB|NS|NB|NL|PE|SK)(?=$|[\s,)\-;])")
# US state codes that are also country codes ("Bengaluru, IN", "Berlin, DE", "Toronto, CA")
AMBIGUOUS_CODES = {"IN", "CA", "DE", "AR", "CO", "IL", "PA", "SC", "MA", "AL", "GA", "ME"}


def _part_status(p: str) -> str:
    if STRONG_US.search(p) or US_TOKEN.search(p):
        return "us"
    if COUNTRY.search(p) or CA_PROVINCE.search(p):
        return "non_us"
    code = STATE_CODE.search(p)
    if FOREIGN_CITY.search(p):
        # "Dublin, OH" and "Paris, TX" are US; "Bengaluru, IN" and "Berlin, DE" are not
        return "us" if code and code.group(1) not in AMBIGUOUS_CODES else "non_us"
    if code:
        return "us"
    return "unknown"


def us_status(location: str) -> str:
    parts = [p.strip() for p in re.split(r";|\n|\||/(?=\s)|\bor\b", location or "") if p.strip()]
    if not parts:
        return "unknown"
    statuses = [_part_status(p) for p in parts]
    if "us" in statuses:
        return "us"
    if all(s == "non_us" for s in statuses):
        return "non_us"
    return "unknown"


def mentions_us_location(text: str) -> bool:
    """For unknown locations: does the description name a US place?"""
    if not text:
        return False
    head = text[:6000]
    return bool(STRONG_US.search(head) or STATE_CODE.search(head) or US_TOKEN.search(head))
