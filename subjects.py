"""
KapturFlow subject registry: shared config for every political figure the
pipeline tracks. rss_collect.py, mediaflow_classify.py, weekly_digest.py,
mediaflow_app.py, and generate_static_page.py all read from this instead of
hardcoding one person's feeds/keywords/arcs.

Kaptur keeps her original (unsuffixed) data file names since that dataset
already exists; new subjects get slug-suffixed file names.
"""

import os
from pathlib import Path

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))


def _gnews(q: str) -> str:
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _bing(q: str) -> str:
    return f"https://www.bing.com/news/search?q={q}&format=rss"


# Shared, reliably-live Ohio statewide/local outlets — reused across subjects
# where relevant rather than re-probed per person.
_OHIO_CAPITAL_JOURNAL = ("Ohio Capital Journal", "https://ohiocapitaljournal.com/feed/")
_CLEVELAND_POLITICS = ("Cleveland.com Politics", "https://www.cleveland.com/arc/outboundfeeds/rss/category/politics/")
_TOLEDO_BLADE = ("Toledo Blade", "https://www.toledoblade.com/rss/")
_WTOL = ("WTOL 11 Toledo", "https://www.wtol.com/feeds/syndication/rss/news")


SUBJECTS = {
    "kaptur": {
        "slug": "kaptur",
        "kind": "person",
        "name": "Rep. Marcy Kaptur",
        "subtitle": "U.S. House, Ohio's 9th District",
        "context": "US Representative Marcy Kaptur (D-Ohio, 9th District, Toledo)",
        "file_suffix": "",  # original unsuffixed files
        "keywords": [
            "kaptur",
            "ohio's 9th",
            "ohio 9th",
            "9th congressional district",
            "oh-9",
            "oh 9th district",
        ],
        "feeds": {
            "Kaptur House.gov":     "https://kaptur.house.gov/rss.xml",
            _TOLEDO_BLADE[0]:       _TOLEDO_BLADE[1],
            _WTOL[0]:               _WTOL[1],
            _OHIO_CAPITAL_JOURNAL[0]: _OHIO_CAPITAL_JOURNAL[1],
            _CLEVELAND_POLITICS[0]:   _CLEVELAND_POLITICS[1],
            "GNews: Marcy Kaptur":          _gnews("%22Marcy+Kaptur%22"),
            "GNews: Kaptur Ohio 9th":       _gnews("Kaptur+%22Ohio%27s+9th%22"),
            "GNews: Kaptur Toledo":         _gnews("Kaptur+Toledo"),
            "GNews: Kaptur committee":      _gnews("Kaptur+committee+appropriations"),
            "GNews: Kaptur bill":           _gnews("Kaptur+bill+legislation"),
            "GNews: Kaptur campaign":       _gnews("Kaptur+campaign+election"),
            "GNews: OH-9 congressional":    _gnews("%22Ohio%27s+9th+congressional+district%22"),
            "Bing: Marcy Kaptur":       _bing("%22Marcy+Kaptur%22"),
            "Bing: Kaptur Toledo":      _bing("Kaptur+Toledo"),
            "Bing: Kaptur Ohio 9th":    _bing("Kaptur+Ohio+9th+district"),
        },
        "newsapi_queries": ["Marcy Kaptur", "Kaptur Ohio 9th district", "Kaptur Toledo"],
        "arcs": ["LEGISLATION", "COMMITTEE", "DISTRICT", "CAMPAIGN", "MEDIA", "UNMAPPED"],
        "arc_label": {
            "LEGISLATION": "Legislation",
            "COMMITTEE":   "Committee",
            "DISTRICT":    "District",
            "CAMPAIGN":    "Campaign",
            "MEDIA":       "Media",
        },
        "arc_color": {
            "LEGISLATION": "#2f5f8a",
            "COMMITTEE":   "#6b4d8a",
            "DISTRICT":    "#2f7a52",
            "CAMPAIGN":    "#a13d3d",
            "MEDIA":       "#b06a24",
        },
        "arc_guide": """  LEGISLATION - bills she sponsors/cosponsors, floor votes, floor statements
  COMMITTEE   - her committee/subcommittee work (e.g. Appropriations), hearings, oversight
  DISTRICT    - local Ohio 9th District news, events, federal funding/projects for the district
  CAMPAIGN    - her campaign, elections, opponents, endorsements, fundraising
  MEDIA       - interviews, op-eds, press statements not tied to a specific bill or hearing""",
        "arc_fallback_rules": [
            ("LEGISLATION", r"\b(bill|act|vote|floor|cosponsor|resolution|amendment)\b"),
            ("COMMITTEE",   r"\b(committee|subcommittee|hearing|appropriations|oversight|ranking member)\b"),
            ("CAMPAIGN",    r"\b(campaign|election|primary|opponent|endorse|fundrais|reelect|challenger)\b"),
            ("DISTRICT",    r"\b(toledo|lucas county|ohio|district|port|shipline|great lakes|grant|funding)\b"),
            ("MEDIA",       r"\b(interview|op-ed|statement|says|said|press release)\b"),
        ],
    },

    "brown": {
        "slug": "brown",
        "kind": "person",
        "name": "Sherrod Brown",
        "subtitle": "Ohio Democrat, former U.S. Senator",
        "context": "Sherrod Brown, Ohio Democrat and former U.S. Senator",
        "file_suffix": "_brown",
        "keywords": [
            "sherrod brown",
        ],
        "feeds": {
            _OHIO_CAPITAL_JOURNAL[0]: _OHIO_CAPITAL_JOURNAL[1],
            _CLEVELAND_POLITICS[0]:   _CLEVELAND_POLITICS[1],
            "GNews: Sherrod Brown":          _gnews("%22Sherrod+Brown%22"),
            "GNews: Sherrod Brown Ohio":     _gnews("Sherrod+Brown+Ohio"),
            "GNews: Sherrod Brown 2026":     _gnews("Sherrod+Brown+2026"),
            "GNews: Sherrod Brown campaign": _gnews("Sherrod+Brown+campaign"),
            "GNews: Sherrod Brown endorses": _gnews("Sherrod+Brown+endorses"),
            "Bing: Sherrod Brown":       _bing("%22Sherrod+Brown%22"),
            "Bing: Sherrod Brown Ohio":  _bing("Sherrod+Brown+Ohio"),
        },
        "newsapi_queries": ["Sherrod Brown", "Sherrod Brown Ohio"],
        "arcs": ["CAMPAIGN", "POLICY", "ENDORSEMENTS", "MEDIA", "RECORD", "UNMAPPED"],
        "arc_label": {
            "CAMPAIGN":     "Campaign",
            "POLICY":       "Policy",
            "ENDORSEMENTS": "Endorsements",
            "MEDIA":        "Media",
            "RECORD":       "Record",
        },
        "arc_color": {
            "CAMPAIGN":     "#a13d3d",
            "POLICY":       "#2f5f8a",
            "ENDORSEMENTS": "#2f7a52",
            "MEDIA":        "#b06a24",
            "RECORD":       "#6b4d8a",
        },
        "arc_guide": """  CAMPAIGN     - his campaign activity, candidacy speculation/announcements, elections, fundraising
  POLICY       - his policy positions and proposals (labor, trade, banking are his signature issues)
  ENDORSEMENTS - endorsements he gives or receives, coalition-building, union/party backing
  MEDIA        - interviews, op-eds, public statements not tied to a specific policy proposal
  RECORD       - his Senate record and past actions being referenced or revisited""",
        "arc_fallback_rules": [
            ("CAMPAIGN",     r"\b(campaign|election|primary|run|candidacy|fundrais|reelect)\b"),
            ("POLICY",       r"\b(bill|act|policy|proposal|labor|trade|bank|tariff)\b"),
            ("ENDORSEMENTS", r"\b(endorse|union|coalition|backing|support)\b"),
            ("RECORD",       r"\b(senate|record|vote|history|former senator)\b"),
            ("MEDIA",        r"\b(interview|op-ed|statement|says|said)\b"),
        ],
    },

    "acton": {
        "slug": "acton",
        "kind": "person",
        "name": "Dr. Amy Acton",
        "subtitle": "Former Ohio Dept. of Health Director",
        "context": "Dr. Amy Acton, former Director of the Ohio Department of Health",
        "file_suffix": "_acton",
        "keywords": [
            "amy acton",
        ],
        "feeds": {
            _OHIO_CAPITAL_JOURNAL[0]: _OHIO_CAPITAL_JOURNAL[1],
            _CLEVELAND_POLITICS[0]:   _CLEVELAND_POLITICS[1],
            "GNews: Amy Acton":            _gnews("%22Amy+Acton%22"),
            "GNews: Amy Acton Ohio":       _gnews("Amy+Acton+Ohio"),
            "GNews: Amy Acton governor":   _gnews("Amy+Acton+governor"),
            "GNews: Amy Acton campaign":   _gnews("Amy+Acton+campaign"),
            "GNews: Amy Acton health":     _gnews("Amy+Acton+health+policy"),
            "Bing: Amy Acton":       _bing("%22Amy+Acton%22"),
            "Bing: Amy Acton Ohio":  _bing("Amy+Acton+Ohio"),
        },
        "newsapi_queries": ["Amy Acton", "Amy Acton Ohio"],
        "arcs": ["CAMPAIGN", "HEALTH_POLICY", "ENDORSEMENTS", "MEDIA", "RECORD", "UNMAPPED"],
        "arc_label": {
            "CAMPAIGN":       "Campaign",
            "HEALTH_POLICY":  "Health Policy",
            "ENDORSEMENTS":   "Endorsements",
            "MEDIA":          "Media",
            "RECORD":         "Record",
        },
        "arc_color": {
            "CAMPAIGN":      "#a13d3d",
            "HEALTH_POLICY": "#2f5f8a",
            "ENDORSEMENTS":  "#2f7a52",
            "MEDIA":         "#b06a24",
            "RECORD":        "#6b4d8a",
        },
        "arc_guide": """  CAMPAIGN      - her campaign activity, elections, fundraising, candidacy developments
  HEALTH_POLICY - her public health policy positions and proposals (her signature area)
  ENDORSEMENTS  - endorsements she gives or receives, coalition-building
  MEDIA         - interviews, op-eds, public statements not tied to a specific policy proposal
  RECORD        - her tenure as Ohio Department of Health Director / COVID-19 response record""",
        "arc_fallback_rules": [
            ("CAMPAIGN",      r"\b(campaign|election|primary|run|candidacy|fundrais)\b"),
            ("HEALTH_POLICY", r"\b(health|policy|proposal|medicaid|hospital|public health)\b"),
            ("ENDORSEMENTS",  r"\b(endorse|coalition|backing|support)\b"),
            ("RECORD",        r"\b(covid|pandemic|department of health|odh|tenure|record)\b"),
            ("MEDIA",         r"\b(interview|op-ed|statement|says|said)\b"),
        ],
    },

    "healthcare": {
        "slug": "healthcare",
        "kind": "issue",
        "name": "Healthcare",
        "subtitle": "Ohio healthcare policy",
        "context": "the Ohio healthcare policy debate (Medicaid, hospital costs, health insurance, rural healthcare access)",
        "file_suffix": "_healthcare",
        "keywords": [
            "ohio healthcare",
            "ohio health care",
            "ohio medicaid",
            "ohio hospital",
            "ohio health insurance",
        ],
        "feeds": {
            _OHIO_CAPITAL_JOURNAL[0]: _OHIO_CAPITAL_JOURNAL[1],
            _CLEVELAND_POLITICS[0]:   _CLEVELAND_POLITICS[1],
            "GNews: Ohio healthcare policy":  _gnews("Ohio+healthcare+policy"),
            "GNews: Ohio Medicaid":           _gnews("Ohio+Medicaid"),
            "GNews: Ohio health care law":    _gnews("Ohio+health+care+legislation"),
            "GNews: Ohio hospital costs":     _gnews("Ohio+hospital+costs"),
            "GNews: Ohio health insurance":   _gnews("Ohio+health+insurance+law"),
            "GNews: Ohio rural healthcare":   _gnews("Ohio+rural+healthcare"),
            "Bing: Ohio healthcare policy":   _bing("Ohio+healthcare+policy"),
            "Bing: Ohio Medicaid":            _bing("Ohio+Medicaid"),
        },
        "newsapi_queries": ["Ohio healthcare policy", "Ohio Medicaid"],
        "arcs": ["LEGISLATIVE", "STAKEHOLDERS", "IMPACT", "POLITICS", "MEDIA", "UNMAPPED"],
        "arc_label": {
            "LEGISLATIVE":   "Legislative",
            "STAKEHOLDERS":  "Stakeholders",
            "IMPACT":        "Impact",
            "POLITICS":      "Politics",
            "MEDIA":         "Media",
        },
        "arc_color": {
            "LEGISLATIVE":  "#2f5f8a",
            "STAKEHOLDERS": "#6b4d8a",
            "IMPACT":       "#2f7a52",
            "POLITICS":     "#a13d3d",
            "MEDIA":        "#b06a24",
        },
        "arc_guide": """  LEGISLATIVE  - bills, resolutions, votes, hearings, regulatory actions related to Ohio healthcare policy
  STAKEHOLDERS - hospitals, insurers, advocacy groups, unions, or officials taking a position for or against
  IMPACT       - concrete effects: cost data, coverage numbers, access changes, real outcomes for Ohioans
  POLITICS     - how the issue is playing electorally, which candidates are using it, polling on it
  MEDIA        - opinion pieces, editorials, interviews, general coverage not fitting the above""",
        "arc_fallback_rules": [
            ("LEGISLATIVE",  r"\b(bill|act|resolution|vote|hearing|regulation|law)\b"),
            ("STAKEHOLDERS", r"\b(hospital|insurer|union|advocacy|association|group)\b"),
            ("IMPACT",       r"\b(cost|coverage|access|patients|outcome|data|study)\b"),
            ("POLITICS",     r"\b(campaign|election|candidate|poll|voters)\b"),
            ("MEDIA",        r"\b(interview|op-ed|editorial|statement|says|said)\b"),
        ],
    },

    "sjr10": {
        "slug": "sjr10",
        "kind": "issue",
        "name": "SJR10",
        "subtitle": "Ohio Senate Joint Resolution 10 & Voter ID",
        "context": "Ohio Senate Joint Resolution 10 (SJR10) and the related Ohio voter ID debate, including positions taken by Ohio state and federal politicians",
        "file_suffix": "_sjr10",
        "keywords": [
            "sjr10",
            "sjr 10",
            "senate joint resolution 10",
            "ohio voter id",
            "voter id ohio",
            "ohio voter identification",
        ],
        "feeds": {
            _OHIO_CAPITAL_JOURNAL[0]: _OHIO_CAPITAL_JOURNAL[1],
            _CLEVELAND_POLITICS[0]:   _CLEVELAND_POLITICS[1],
            "GNews: SJR10 Ohio":                    _gnews("SJR10+Ohio"),
            "GNews: Ohio Senate Joint Resolution 10": _gnews("Ohio+%22Senate+Joint+Resolution+10%22"),
            "GNews: SJR 10 Ohio":                   _gnews("%22SJR+10%22+Ohio"),
            "GNews: Ohio voter ID law":              _gnews("Ohio+voter+ID+law"),
            "GNews: Ohio voter ID legislation":      _gnews("Ohio+voter+ID+legislation"),
            "GNews: Ohio voter ID Congress":         _gnews("Ohio+voter+ID+Congress"),
            "GNews: Ohio voter ID senator":          _gnews("Ohio+voter+ID+senator"),
            "GNews: Ohio voter ID governor":         _gnews("Ohio+voter+ID+governor"),
            "GNews: Ohio Secretary of State voter ID": _gnews("Ohio+Secretary+of+State+voter+ID"),
            "GNews: Ohio voter ID lawmaker":         _gnews("Ohio+voter+ID+lawmaker"),
            "Bing: SJR10 Ohio":                     _bing("SJR10+Ohio"),
            "Bing: Ohio Senate Joint Resolution 10": _bing("Ohio+Senate+Joint+Resolution+10"),
            "Bing: Ohio voter ID law":               _bing("Ohio+voter+ID+law"),
            "Bing: Ohio voter ID politician":        _bing("Ohio+voter+ID+politician"),
        },
        "newsapi_queries": ["SJR10 Ohio", "Ohio Senate Joint Resolution 10", "Ohio voter ID law"],
        "arcs": ["LEGISLATIVE", "STAKEHOLDERS", "POLITICIAN_STATEMENTS", "IMPACT", "POLITICS", "MEDIA", "UNMAPPED"],
        "arc_label": {
            "LEGISLATIVE":            "Legislative",
            "STAKEHOLDERS":           "Stakeholders",
            "POLITICIAN_STATEMENTS":  "Politician Statements",
            "IMPACT":                 "Impact",
            "POLITICS":               "Politics",
            "MEDIA":                  "Media",
        },
        "arc_color": {
            "LEGISLATIVE":           "#2f5f8a",
            "STAKEHOLDERS":          "#6b4d8a",
            "POLITICIAN_STATEMENTS": "#c46a1f",
            "IMPACT":                "#2f7a52",
            "POLITICS":              "#a13d3d",
            "MEDIA":                 "#b06a24",
        },
        "arc_guide": """  LEGISLATIVE           - the resolution's procedural status: committee action, votes, sponsors, amendments
  STAKEHOLDERS          - advocacy groups, coalitions, or organizations (not elected officials) taking a position for or against SJR10 or Ohio voter ID
  POLITICIAN_STATEMENTS - opinions, votes, or decisions by named federal or Ohio state politicians specifically about voter ID in Ohio
  IMPACT                - concrete effects if enacted: what SJR10 or a voter ID law would actually change and for whom
  POLITICS               - how the resolution/voter ID debate is playing electorally, which candidates are using it, polling
  MEDIA                  - opinion pieces, editorials, interviews, general coverage not fitting the above""",
        "arc_fallback_rules": [
            ("LEGISLATIVE",           r"\b(resolution|committee|vote|hearing|sponsor|amendment)\b"),
            ("POLITICIAN_STATEMENTS", r"\b(senator|representative|rep\.|sen\.|governor|congressman|congresswoman|lawmaker)\b"),
            ("STAKEHOLDERS",          r"\b(coalition|advocacy|group|union|association|aclu|common cause|oppose|support)\b"),
            ("IMPACT",                r"\b(would|impact|effect|change|outcome)\b"),
            ("POLITICS",              r"\b(campaign|election|candidate|poll|voters|ballot)\b"),
            ("MEDIA",                 r"\b(interview|op-ed|editorial|statement|says|said)\b"),
        ],
    },
}

SUBJECT_GROUPS = {
    "politicians": ["kaptur", "brown", "acton"],
    "issues": ["healthcare", "sjr10"],
}
SUBJECT_ORDER = SUBJECT_GROUPS["politicians"] + SUBJECT_GROUPS["issues"]


def get_subject(slug: str) -> dict:
    if slug not in SUBJECTS:
        raise ValueError(f"Unknown subject '{slug}'. Choices: {', '.join(SUBJECTS)}")
    return SUBJECTS[slug]


def paths_for(slug: str) -> dict[str, Path]:
    suffix = get_subject(slug)["file_suffix"]
    return {
        "log":        DATA_DIR / f"mediaflow_log{suffix}.txt",
        "seen":       DATA_DIR / f"mediaflow_seen{suffix}.json",
        "items":      DATA_DIR / f"mediaflow_items{suffix}.json",
        "classified": DATA_DIR / f"mediaflow_classified{suffix}.json",
        "digest":     DATA_DIR / f"mediaflow_digest{suffix}.json",
        "lock":       DATA_DIR / f".collect_lock{suffix}",
    }
