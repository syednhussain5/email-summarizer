import re
from typing import Dict, List, Any, Tuple, Set
from datetime import datetime
import dateparser

def _normalize_links(text: str) -> List[str]:
    # capture typical URLs and remove trailing punctuation
    raw_links = re.findall(r'(https?://[^\s)]+)', text)
    clean = []
    for l in raw_links:
        l = l.rstrip(').,;"\'\n')
        if l not in clean:
            clean.append(l)
    return clean

def _clean_text(text: str) -> str:
    # remove urls inline, collapse whitespace, strip boilerplate-like artifacts
    text_wo_links = re.sub(r'https?://[^\s)]+', '', text)
    text_wo_links = re.sub(r'[\t\r]', ' ', text_wo_links)
    text_wo_links = re.sub(r'\s+', ' ', text_wo_links)
    return text_wo_links.strip()

def _split_sentences(text: str) -> List[str]:
    # simple split on punctuation and newlines
    parts = re.split(r'[\n\.!?]+', text)
    return [p.strip(' :\u2022-') for p in parts if p and p.strip()]


STOPWORDS: Set[str] = set(
    '''a an the and or but if while of in on at for from to with as by into over after before about is are was were be been being
    this that these those there here it its they them their you your we our i me my us will shall can could should would may might
    not no yes please kindly dear sir madam hello hi regards thanks thank hereby above below also etc etc.'''.split()
)

ACTION_HINTS: Set[str] = {
    'apply', 'register', 'submit', 'enroll', 'attend', 'pay', 'upload', 'fill', 'complete', 'verify', 'participate', 'join'
}

DEADLINE_HINTS: Set[str] = {
    'deadline', 'last date', 'last-day', 'last day', 'by', 'before', 'due', 'closing', 'closes', 'ends'
}

BOILERPLATE_PATTERNS: List[Tuple[str, str]] = [
    (r"\bhello\s+[a-zA-Z .'-]+,?\s*", ""),
    (r"\bhi\s+[a-zA-Z .'-]+,?\s*", ""),
    (r"\bdear\s+[a-zA-Z .'-]+,?\s*", ""),
    (r"\bclick here\b", ""),
    (r"\bclick the link\b", ""),
    (r"\bfor more (details|information).*", ""),
    (r"\bread more\b", ""),
    (r"\bkindly note\b", ""),
    (r"\bplease note\b", ""),
]

def _remove_boilerplate(text: str) -> str:
    cleaned = text
    for pat, rep in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()

# --- Abstractive helpers ---
CANONICAL_ACTIONS = [
    (re.compile(r"extended|extension|postponed|rescheduled", re.I), "deadline extended"),
    (re.compile(r"opens|open|commence|start", re.I), "registration opens"),
    (re.compile(r"close|closing|ends|last date|deadline|due", re.I), "registration deadline"),
    (re.compile(r"payment|fee|fees|pay", re.I), "fee payment"),
    (re.compile(r"exam|examination", re.I), "exam update"),
    (re.compile(r"workshop|seminar|webinar|orientation|session", re.I), "event announcement"),
    (re.compile(r"submit|submission|upload|fill|apply|register|enrol|enroll", re.I), "action required"),
]

GENERIC_WORDS: Set[str] = set("notice update information details course courses department college student students university office".split())

def _extract_keywords(text: str, top_n: int = 6) -> List[str]:
    tokens = _tokenize(text)
    freq: Dict[str, int] = {}
    for i, t in enumerate(tokens):
        if t in STOPWORDS or t in GENERIC_WORDS or len(t) < 3:
            continue
        freq[t] = freq.get(t, 0) + 1
        # boost consecutive bigrams
        if i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt not in STOPWORDS and nxt not in GENERIC_WORDS and len(nxt) >= 3:
                bigram = f"{t} {nxt}"
                freq[bigram] = freq.get(bigram, 0) + 1
    if not freq:
        return []
    scored = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    keywords: List[str] = []
    used: Set[str] = set()
    for term, _ in scored:
        # avoid overlapping with already chosen
        if any(term in u or u in term for u in used):
            continue
        keywords.append(term)
        used.add(term)
        if len(keywords) >= top_n:
            break
    return keywords

def _detect_action(text: str) -> str:
    for pattern, canonical in CANONICAL_ACTIONS:
        if pattern.search(text):
            return canonical
    # fallback based on hints
    tl = text.lower()
    if any(h in tl for h in ACTION_HINTS):
        return "action required"
    return "update"

def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z\-']+", text.lower())

def _compress_sentence(s: str) -> str:
    # remove extra spaces, bracketed refs, leading bullets, email artefacts
    s = re.sub(r"\[[^\]]+\]", '', s)
    s = re.sub(r"\([^\)]+\)", '', s)
    s = re.sub(r"^[-•:]+\s*", '', s.strip())
    s = re.sub(r"\s+", ' ', s).strip()
    # capitalize first letter
    if s:
        s = s[0].upper() + s[1:]
    return s

def _sentence_score(s: str, word_freq: Dict[str, float]) -> float:
    tokens = _tokenize(s)
    if not tokens:
        return 0.0
    score = 0.0
    for t in tokens:
        if t in STOPWORDS:
            continue
        score += word_freq.get(t, 0.0)
    score /= max(len(tokens), 6)
    # bonuses for actionability and deadlines
    lower = s.lower()
    if any(h in lower for h in ACTION_HINTS):
        score *= 1.2
    if any(h in lower for h in DEADLINE_HINTS):
        score *= 1.2
    # penalize extremely long lines
    if len(s) > 220:
        score *= 0.85
    return score

def _build_word_freq(sentences: List[str]) -> Dict[str, float]:
    freq: Dict[str, int] = {}
    for s in sentences:
        for t in _tokenize(s):
            if t in STOPWORDS or t.isdigit():
                continue
            freq[t] = freq.get(t, 0) + 1
    if not freq:
        return {}
    max_f = max(freq.values())
    return {k: v / max_f for k, v in freq.items()}

def _paraphrase(lines: List[str]) -> List[str]:
    """Lightweight rule-based paraphrasing to avoid exact phrasing.
    - Replace formalities with neutral terms
    - Normalize dates keywords
    - Convert passive-ish constructions to imperative where possible
    """
    replacements = [
        (r"hereby|kindly|please be informed that", ""),
        (r"this is to inform|this is to notify", ""),
        (r"registration|enrolment", "registration"),
        (r"examination", "exam"),
        (r"has been|have been", "is"),
        (r"is extended(?:\s+(till|until|to))?", "deadline extended"),
        (r"last date", "deadline"),
        (r"students are requested to", "students should"),
        (r"you are requested to", "please"),
        (r"shall", "will"),
    ]
    out: List[str] = []
    for s in lines:
        t = s
        for pat, rep in replacements:
            t = re.sub(pat, rep, t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        if t and t[-1] not in ".!?":
            t += "."
        out.append(t)
    return out

def _extract_datetime_hint(text: str) -> Tuple[str, str]:
    dt = dateparser.parse(
        text,
        settings={
            'PREFER_DATES_FROM': 'future',
            'DATE_ORDER': 'DMY',
            'TIMEZONE': 'Asia/Kolkata',
            'RETURN_AS_TIMEZONE_AWARE': False
        }
    )
    if not dt:
        return None, None
    return dt.strftime("%Y-%m-%d"), dt.strftime("%I:%M %p")

# --- Key details extractors ---
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?91[- ]?)?[6-9]\d{9}")
CURRENCY_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*)(?:\.[0-9]{1,2})?", re.I)

DOC_HINTS = [
    "id card", "aadhar", "aadhaar", "bonafide", "photo", "photograph", "passport size",
    "hall ticket", "admit card", "marksheet", "mark sheet", "resume", "cv",
    "payment receipt", "fee receipt", "signature", "consent form"
]

AUDIENCE_PATTERNS: List[re.Pattern] = [
    re.compile(r"for\s+(all\s+)?(ug|pg|b\.?tech|m\.?tech|mca|mba|phd)\s+students", re.I),
    re.compile(r"for\s+(first|second|third|final)\s+year\s+students", re.I),
    re.compile(r"for\s+([a-z&/ ]+?)\s+students", re.I),
    re.compile(r"only\s+for\s+([a-z&/ ]+?)\s+students", re.I),
    re.compile(r"eligible\s+for\s+([a-z&/ ]+?)\s+students", re.I),
]

VENUE_RE = re.compile(r"(?:venue|place|at)[:\- ]+([^\n,\.]{3,80})", re.I)

FORM_LINK_HINTS = [
    "forms.gle", "docs.google.com/forms", "forms.office.com", "tinyurl.com", "form"  # last is generic
]

def _extract_contacts(text: str) -> Tuple[List[str], List[str]]:
    emails = EMAIL_RE.findall(text)
    phones = PHONE_RE.findall(text)
    # normalize phone spacing
    phones = [re.sub(r"\s+", "", p) for p in phones]
    # dedupe while preserving order
    seen = set()
    emails = [e for e in emails if not (e in seen or seen.add(e))]
    seen.clear()
    phones = [p for p in phones if not (p in seen or seen.add(p))]
    return emails[:3], phones[:3]

def _extract_fee(text: str) -> str:
    m = CURRENCY_RE.search(text)
    if m:
        amt = m.group(1)
        # add thousands separators if missing
        try:
            normalized = f"₹{int(amt.replace(',', '')):,}"
        except Exception:
            normalized = f"₹{amt}"
        # check context to ensure it refers to fee/payment
        window = text[max(0, m.start()-25):m.end()+25].lower()
        if any(k in window for k in ["fee", "fees", "payment", "pay", "amount"]):
            return normalized
    # textual amounts like 'no fee' / 'free'
    if re.search(r"no\s+fee|free\b", text, re.I):
        return "No fee"
    return None

def _extract_audience(text: str) -> str:
    for pat in AUDIENCE_PATTERNS:
        m = pat.search(text)
        if m:
            grp = m.group(0)
            return _compress_sentence(grp)
    return None

def _extract_required_docs(text: str) -> List[str]:
    found: List[str] = []
    tl = text.lower()
    for hint in DOC_HINTS:
        if hint in tl:
            found.append(hint)
    # also look for phrases like 'carry X' / 'bring X'
    carry_m = re.findall(r"(?:carry|bring|submit|upload)\s+([^\.;\n]{3,60})", text, re.I)
    for frag in carry_m:
        # split by commas to get individual items if present
        parts = [p.strip() for p in re.split(r",| and ", frag) if p.strip()]
        for p in parts:
            if len(p) <= 2:
                continue
            found.append(p.lower())
    # dedupe
    dedup: List[str] = []
    seen: Set[str] = set()
    for d in found:
        if d not in seen:
            dedup.append(d)
            seen.add(d)
    return dedup[:5]

def _extract_venue(text: str) -> str:
    m = VENUE_RE.search(text)
    if m:
        v = m.group(1).strip()
        return _compress_sentence(v)
    # other patterns like 'in Auditorium' or 'at Block X'
    m2 = re.search(r"\b(in|at)\s+(Auditorium|Seminar Hall|Main Hall|Block [A-Z]|Room [0-9A-Z-]+)\b", text, re.I)
    if m2:
        return _compress_sentence(m2.group(0))
    return None

def _select_form_link(links: List[str]) -> str:
    for l in links:
        ll = l.lower()
        if any(h in ll for h in FORM_LINK_HINTS):
            return l
    return None

def _find_actions(sentences: List[str]) -> List[str]:
    actionable: List[str] = []
    for s in sentences:
        low = s.lower()
        if any(h in low for h in ACTION_HINTS):
            actionable.append(_compress_sentence(s))
    # prefer shorter, directive-like items
    actionable = sorted(actionable, key=lambda x: (len(x), x))
    return actionable[:3]


def summarize_text(text: str) -> Dict[str, Any]:
    """Produce a structured bullet-point summary noting key details.
    Returns dict with summary lines, links, and detected date/time.
    """
    if not text or not text.strip():
        return {"summary": [], "links": []}

    links = _normalize_links(text)
    clean_text = _remove_boilerplate(_clean_text(text))

    # extract date/time from overall body
    date_str, time_str = _extract_datetime_hint(clean_text)
    
    # Enhanced date detection - try multiple patterns and approaches
    if not date_str:
        # Try various date patterns
        date_patterns = [
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',  # DD/MM/YYYY or DD-MM-YYYY
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',    # YYYY/MM/DD or YYYY-MM-DD
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})',  # DD Mon YYYY
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4})',  # Mon DD, YYYY
        ]
        
        for pattern in date_patterns:
            email_date_match = re.search(pattern, clean_text, re.IGNORECASE)
            if email_date_match:
                try:
                    dt = dateparser.parse(email_date_match.group(1), settings={
                        'PREFER_DATES_FROM': 'future',
                        'DATE_ORDER': 'DMY',
                        'TIMEZONE': 'Asia/Kolkata',
                        'RETURN_AS_TIMEZONE_AWARE': False
                    })
                    if dt:
                        date_str = dt.strftime("%Y-%m-%d")
                        break
                except Exception:
                    continue
        
        # If still no date, try parsing the entire text with more lenient settings
        if not date_str:
            try:
                dt = dateparser.parse(clean_text, settings={
                    'PREFER_DATES_FROM': 'future',
                    'DATE_ORDER': 'DMY',
                    'TIMEZONE': 'Asia/Kolkata',
                    'RETURN_AS_TIMEZONE_AWARE': False,
                    'STRICT_PARSING': False
                })
                if dt:
                    date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

    # candidate sentences
    sentences = _split_sentences(clean_text)

    # intent/action detection and keywords for abstractive lines
    action = _detect_action(clean_text)
    keywords = _extract_keywords(clean_text, top_n=5)

    # additional key details
    emails, phones = _extract_contacts(clean_text)
    fee = _extract_fee(clean_text)
    audience = _extract_audience(clean_text)
    venue_hint = _extract_venue(clean_text)
    action_points = _find_actions(sentences)
    form_link = _select_form_link(links)
    required_docs = _extract_required_docs(clean_text)

    bullets: List[str] = []

    if keywords:
        bullets.append(f"Topic: {', '.join(keywords[:3])}.")
    else:
        bullets.append(f"Update: {action}.")

    if action_points:
        bullets.append(f"Action: {action_points[0]}" if not action_points[0].endswith('.') else f"Action: {action_points[0]}")
    else:
        # fallback to canonical action
        if action and action != "update":
            bullets.append(f"Action: {action}.")

    # when/where
    def _fmt_date_human(ds: str) -> str:
        try:
            d = datetime.strptime(ds, "%Y-%m-%d")
            return d.strftime("%d %b %Y (%a)")
        except Exception:
            return ds

    # Always show date/time if found
    if date_str and time_str:
        bullets.append(f"WHEN: {_fmt_date_human(date_str)} {time_str}.")
    elif date_str:
        bullets.append(f"WHEN: {_fmt_date_human(date_str)}.")
    elif time_str:
        bullets.append(f"WHEN: {time_str}.")



    if audience:
        bullets.append(f"Who: {audience}.")

    if fee:
        bullets.append(f"Fee: {fee}.")

    if required_docs:
        bullets.append(f"Required: {', '.join(required_docs[:3])}.")



    # indicate presence of form without duplicating link in bullets (links are shown separately)
    if form_link:
        bullets.append("Form: available in links below.")

    # keep it concise
    bullets = [b.strip() for b in bullets if b.strip()]
    bullets = bullets[:8]

    return {
        "summary": bullets,
        "links": links,
        "date": date_str,
        "time": time_str,
    }
