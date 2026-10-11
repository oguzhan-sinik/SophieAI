"""Controller-owned runtime support compiled into every workflow.

Nothing here comes from a brief. It encodes observed platform behaviour and plain English calendar
language, so that model-written policy code receives usable values:

- response_mapping stores scalars only; a mapped list/object must be materialised for code nodes.
- Business-day arithmetic written by a model has been wrong often enough that it is provided here;
  the weekdays and excluded dates are always arguments the generated code takes from its source.
- The platform resolves a `date` extraction against the real clock, not the call's `now` variable,
  so "tomorrow" lands on the wrong day whenever a call is simulated on another date. Spoken dates
  are therefore captured as the customer's words and resolved here against `now`.
- Callers talk like people: a number in two parts, a correction, a story with a number in it, an
  amount or a date in words. The helpers read those words in English and in Turkish, so that no
  extraction model has to do arithmetic on what was said. An amount is captured as words too.
- The compiled agent is sent as one request. The helpers are therefore compiled into a code stage
  only where that stage needs them, not into every stage.
"""
import ast
import json
import re

START = "# controller: runtime prelude"
END = "# controller: end of runtime prelude"
SAID = ("If the customer states a complete calendar date including its year, give it as YYYY-MM-DD. Otherwise give the customer's own final "
        "words for the day exactly as said, in the customer's own language and never translated (for example: tomorrow, this Friday, the 26th, "
        "6 November, yarın, bu cuma, ayın 26'sı) and do not work out a calendar date yourself.")
# Words are captured, so without this a period would count as a given day in every `is_set` route.
SINGLE_DAY = ("Extract only the date for the current requested slot; ignore dates of appointments, other products or unrelated stories. A correction replaces the previous date. Fill this only when the words name one single day. A period or a condition (for example: next week, the week after next, "
              "end of the month, in a few days, when my salary comes) is not a day: leave this variable out entirely.")
SAID_AMOUNT = ("Give the customer's own final words for the amount of money exactly as said, in the customer's own language, in digits or in words, "
               "with the currency if it was said (for example: 1.250,50 TL, bin iki yüz elli lira, four hundred and fifty-five). Do not calculate, convert or translate.")
# The same reason as for days: a number in a story must not become the proposal.
ONE_AMOUNT = ("Fill this only with an amount the customer proposes or accepts to pay in answer to the current question. An amount in a story about something else "
              "(what was paid before, a salary, a price, an expense) is not it. A correction replaces the earlier amount. A reference without a number "
              "(the full amount, the minimum, half of it) is not an amount: leave this variable out entirely.")

# Pure calendar arithmetic. Interpretation of ambiguous wording is a parameter, never a constant:
# policy code may call ctl_date again with the reading its own source prescribes.
DATE_HELPERS = '''
import datetime
import re
CTL_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
             "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
CTL_ORDINALS = ["zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
                "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
                "nineteenth"]
CTL_TENS = dict(twenty=20, thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90, twentieth=20, thirtieth=30)
CTL_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
              "november", "december"]
CTL_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def ctl_numbers(tokens):
    found = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        value = None
        ordinal = False
        width = 1
        if tok.isdigit():
            value = int(tok)
            if i + 1 < len(tokens) and tokens[i + 1] in ("st", "nd", "rd", "th"):
                ordinal = True
                width = 2
        elif tok in CTL_TENS:
            value = CTL_TENS[tok]
            ordinal = tok.endswith("ieth")
            if i + 1 < len(tokens) and not ordinal:
                nxt = tokens[i + 1]
                if nxt in CTL_UNITS[1:10]:
                    value += CTL_UNITS.index(nxt)
                    width = 2
                elif nxt in CTL_ORDINALS[1:10]:
                    value += CTL_ORDINALS.index(nxt)
                    ordinal = True
                    width = 2
        elif tok in CTL_ORDINALS:
            value = CTL_ORDINALS.index(tok)
            ordinal = True
        elif tok in CTL_UNITS:
            value = CTL_UNITS.index(tok)
        if value is not None:
            found.append([value, ordinal, i, i + width])
        i += width
    return found


def ctl_year_spans(tokens, numbers, after):
    """[year, first token, token after its last] for each year the phrase states: in digits anywhere,
    or in words after position `after` (nineteen eighty eight, one nine eight eight, two thousand and five)."""
    found = [[n[0], n[2], n[3]] for n in numbers if 1900 <= n[0] <= 2100]
    plain = [n for n in numbers if not n[1] and n[2] > after]
    for pos in range(len(plain) - 1):
        first = plain[pos]
        second = plain[pos + 1]
        gap = tokens[first[3]:second[2]]
        year = None
        if first[0] in (19, 20) and not gap and 10 <= second[0] <= 99:
            year = first[0] * 100 + second[0]
        elif first[0] in (19, 20) and gap in (["oh"], ["o"]) and 1 <= second[0] <= 9:
            year = first[0] * 100 + second[0]
        elif first[0] in (1, 2) and gap in (["thousand"], ["thousand", "and"]) and second[0] <= 99:
            year = first[0] * 1000 + second[0]
        if year is not None:
            found.append([year, first[2], second[3]])
    digits = [CTL_UNITS.index(tok) if tok in CTL_UNITS[:10] else (0 if tok in ("oh", "o") else None) for tok in tokens]
    for pos in range(max(after + 1, 0), len(tokens) - 3):
        run = digits[pos:pos + 4]
        if None not in run:
            found.append([run[0] * 1000 + run[1] * 100 + run[2] * 10 + run[3], pos, pos + 4])
    if not found and "thousand" in tokens[max(after + 1, 1):] and tokens[tokens.index("thousand") - 1] == "two":
        found.append([2000, tokens.index("thousand") - 1, tokens.index("thousand") + 1])
    return [span for span in found if 1900 <= span[0] <= 2100]


def ctl_years(tokens, numbers, after):
    return [span[0] for span in ctl_year_spans(tokens, numbers, after)]


def ctl_month(tok):
    """1-12 for a month name or its three- or four-letter short form, else 0."""
    for index, name in enumerate(CTL_MONTHS):
        if tok == name or (len(tok) >= 3 and tok != "may" and name.startswith(tok) and tok in (name[:3], name[:4])):
            return index + 1
    return 0


def ctl_build(year, month, day):
    try:
        return datetime.date(year, month, day)
    except Exception:
        return None


def ctl_date(said, call_now, next_weekday="following_week"):
    """Resolve a spoken day against the call date. Returns YYYY-MM-DD, or '' when no single day is named.
    What follows the last correction word is read first: 'the 21st, sorry, I mean the 20th' is the 20th."""
    try:
        base = datetime.date.fromisoformat(str(call_now)[:10])
        whole = str(said or "")
        turkish = ctl_turkish(whole)
        parts = ctl_said_parts(whole)
        if len(parts) > 1:
            for index in range(len(parts) - 1, -1, -1):
                found = ctl_day(parts[index], base, next_weekday, turkish)
                if found:
                    return found
        return ctl_day(whole, base, next_weekday, turkish)
    except Exception:
        return ""


def ctl_day(said, base, next_weekday, turkish=None):
    """One reading of the words, for ctl_date. base is the call's date."""
    text = str(said or "").lower()
    iso = re.search(r"(\\d{4})-(\\d{2})-(\\d{2})", text)
    if iso:
        exact = ctl_build(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return exact.isoformat() if exact else ""
    numeric = ctl_numeric_date(text, base)
    if numeric:
        return numeric
    text = str(ctl_tr(said, turkish) or "").lower()
    tokens = re.findall(r"[a-z]+|\\d+", text.replace("-", " "))
    if not tokens:
        return ""
    numbers = ctl_numbers(tokens)
    month = None
    for pos, tok in enumerate(tokens):
        if ctl_month(tok):
            month = [ctl_month(tok), pos]
    days = [n for n in numbers if 1 <= n[0] <= 31]
    near = []
    if month:
        # A month counts only with a day number beside it ("may" is also an ordinary verb).
        near = [n for n in days if n[3] == month[1] or n[2] == month[1] + 1
                or (n[3] + 1 == month[1] and tokens[n[3]] == "of")
                or (n[2] == month[1] + 2 and tokens[month[1] + 1] == "the")]
    if near:
        pick = near[0]
        # A stated year is kept whatever it is: a date of birth lies decades before the call.
        years = ctl_years(tokens, numbers, max(month[1], pick[3] - 1))
        year = years[0] if years else base.year
        day = ctl_build(year, month[0], pick[0])
        if day and not years and day < base:
            day = ctl_build(year + 1, month[0], pick[0])
        return day.isoformat() if day else ""
    joined = " ".join(tokens)
    amount = None
    span = re.search(r"\\bin (\\w+(?: \\w+)?) (day|days|week|weeks)\\b", joined)
    if span:
        count = ctl_numbers(span.group(1).split())
        amount = count[0][0] if count else (1 if span.group(1) in ("a", "an") else None)
        if amount is not None:
            return (base + datetime.timedelta(days=amount * (7 if span.group(2).startswith("week") else 1))).isoformat()
    marked = [n for n in days if n[1] or (n[2] > 0 and tokens[n[2] - 1] == "the")]
    if marked:
        want = marked[-1][0]
        year, mon = base.year, base.month
        if "next month" in joined:
            year, mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
        for step in range(3):
            day = ctl_build(year, mon, want)
            if day and day >= base:
                return day.isoformat()
            mon += 1
            if mon > 12:
                year, mon = year + 1, 1
        return ""
    for pos, tok in enumerate(tokens):
        hit = [i for i, name in enumerate(CTL_DAYS) if tok == name or tok == name[:3] or tok == name[:4]]
        if not hit:
            continue
        before = tokens[pos - 1] if pos else ""
        monday = base - datetime.timedelta(days=base.weekday())
        # "Tuesday next week" names its week itself, whatever "next Tuesday" is read as.
        if "next week" in joined:
            return (monday + datetime.timedelta(days=7 + hit[0])).isoformat()
        if before == "next" and next_weekday == "following_week":
            return (monday + datetime.timedelta(days=7 + hit[0])).isoformat()
        if before == "this":
            return (monday + datetime.timedelta(days=hit[0])).isoformat()
        ahead = (hit[0] - base.weekday()) % 7
        if before == "next" and ahead == 0:
            ahead = 7
        return (base + datetime.timedelta(days=ahead)).isoformat()
    if "day after tomorrow" in joined:
        return (base + datetime.timedelta(days=2)).isoformat()
    if "tomorrow" in tokens:
        return (base + datetime.timedelta(days=1)).isoformat()
    if "today" in tokens or "tonight" in tokens or "right now" in joined or "immediately" in tokens:
        return base.isoformat()
    return ""


def ctl_as_day(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def ctl_is_business_day(day, weekdays, excluded):
    """True when the day falls on one of the weekdays (Monday=0) and is not an excluded date."""
    try:
        found = ctl_as_day(day)
        return found is not None and found.weekday() in [int(w) for w in weekdays] and found.isoformat() not in [str(x)[:10] for x in excluded]
    except Exception:
        return False


def ctl_add_business_days(day, count, weekdays, excluded):
    """The count-th business day strictly after day, as YYYY-MM-DD; '' when it cannot be worked out."""
    try:
        found = ctl_as_day(day)
        left = int(count)
        if found is None or left < 1:
            return ""
        for step in range(3700):
            found = found + datetime.timedelta(days=1)
            if ctl_is_business_day(found.isoformat(), weekdays, excluded):
                left -= 1
                if left == 0:
                    return found.isoformat()
        return ""
    except Exception:
        return ""


def ctl_business_day_on_or_after(day, weekdays, excluded):
    """The day itself when it is a business day, otherwise the next business day."""
    try:
        found = ctl_as_day(day)
        if found is None:
            return ""
        if ctl_is_business_day(found.isoformat(), weekdays, excluded):
            return found.isoformat()
        return ctl_add_business_days(found.isoformat(), 1, weekdays, excluded)
    except Exception:
        return ""


def ctl_last_business_day_of_week(day, weekdays, excluded):
    """The last business day of the Monday-to-Sunday week containing day; '' when that week has none."""
    try:
        found = ctl_as_day(day)
        if found is None:
            return ""
        monday = found - datetime.timedelta(days=found.weekday())
        for back in range(6, -1, -1):
            candidate = (monday + datetime.timedelta(days=back)).isoformat()
            if ctl_is_business_day(candidate, weekdays, excluded):
                return candidate
        return ""
    except Exception:
        return ""
'''

SPEECH_HELPERS = r'''
# Speech in the caller's own language: English and Turkish are read. Nothing here knows a bank, a product or a policy.
CTL_FOLD = [["İ", "i"], ["ı", "i"], ["Ş", "s"], ["ş", "s"], ["Ğ", "g"], ["ğ", "g"],
            ["Ü", "u"], ["ü", "u"], ["Ö", "o"], ["ö", "o"], ["Ç", "c"], ["ç", "c"],
            ["Â", "a"], ["â", "a"], ["Î", "i"], ["î", "i"], ["Û", "u"], ["û", "u"],
            ["’", "'"], ["‘", "'"], ["´", "'"], ["`", "'"], ["̇", ""]]
CTL_TR_LETTERS = "ıİşŞğĞçÇöÖüÜ"
# Longest stem first: a word is matched whole, or as a stem with one of the endings below.
CTL_TR_NUMBERS = [["milyon", 1000000, "million"], ["altmis", 60, "ten"], ["yetmis", 70, "ten"], ["seksen", 80, "ten"],
                  ["doksan", 90, "ten"], ["yirmi", 20, "ten"], ["sifir", 0, "unit"], ["sekiz", 8, "unit"],
                  ["dokuz", 9, "unit"], ["otuz", 30, "ten"], ["kirk", 40, "ten"], ["elli", 50, "ten"],
                  ["dort", 4, "unit"], ["dord", 4, "unit"], ["alti", 6, "unit"], ["yedi", 7, "unit"],
                  ["bir", 1, "unit"], ["iki", 2, "unit"], ["bes", 5, "unit"], ["yuz", 100, "hundred"],
                  ["bin", 1000, "thousand"], ["uc", 3, "unit"], ["on", 10, "ten"]]
CTL_TR_MONTHS = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
CTL_TR_DAYS = ["pazartesi", "sali", "carsamba", "persembe", "cumartesi", "cuma", "pazar"]
CTL_TR_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "saturday", "friday", "sunday"]
# Words long enough that no English word is one of them with an ending.
CTL_TR_LONG = ["subat", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "kasim", "aralik",
               "pazartesi", "carsamba", "persembe", "cumartesi", "pazar"]
CTL_TR_SIGNS = ["bugun", "yarin", "yarindan", "haftaya", "hafta", "ayin", "sonra", "gelecek", "onumuzdeki", "obur",
                "lira", "kurus", "bucuk", "tl", "hayir", "evet", "degil", "tamam", "icin", "kadar", "ama", "simdi",
                "olur", "olmaz", "cift", "tarihinde", "odeyebilirim", "odeyecegim", "odeyemem", "odeme"]
# What may follow a number: its possessive or ordinal ending, then a case ending (altisi, altisinda, altinci, besinde).
# With the first it is a day of the month ("on birinde"); with a case ending alone it is a time of day ("on birde").
CTL_TR_NUMBER_END = r"(s?[iu]|[iu]?nc[iu])?(n?[dt][ae]n?|n?[ae]|y[ae]|n?[iu]n|[ny]?[iu])?"
CTL_TR_WORD_END = r"(?:n?[iu]n|[dt][ae]n?|n?[ae]|y[ae]|y?[iu]|s[iu])?"
# A caller who corrects himself says one of these, and what follows is what he means.
CTL_CORRECTIONS = (r"\b(?:no wait|wait no|i mean|i meant|scratch that|make that|ozur dilerim|daha dogrusu|sorry|correction"
                   r"|rather|actually|pardon|yani|hayir|yok|no|duzeltiyorum|duzelteyim|yanlis|affedersiniz|aslinda|degil)\b")
CTL_MAJOR = ["lira", "dolar", "dollar", "euro", "avro", "pound", "sterlin", "buck", "quid"]
CTL_MINOR = ["kurus", "cent", "penn", "pence"]
CTL_FILLERS = ["and", "ve", "uh", "um", "er", "erm", "hmm", "eh", "ee", "eee", "sey"]
# Correction words that are as often only a filler: they order the reading, they do not take anything back.
CTL_SOFT = ["yani", "actually", "aslinda", "rather", "degil"]


def ctl_fold(text):
    """Lower case, with Turkish letters written as plain ones, so a transcript with or without them reads the same."""
    folded = str(text or "")
    for pair in CTL_FOLD:
        folded = folded.replace(pair[0], pair[1])
    return folded.lower()


def ctl_tr_number(tok):
    """[value, kind, ending] for a Turkish number word, else None. ending is 0 for none, 1 for a possessive or
    ordinal ending (altisi, altisinda, altinci), 2 for a case ending alone (altida, altiya)."""
    for word in CTL_TR_NUMBERS:
        if tok == word[0]:
            return [word[1], word[2], 0]
    for word in CTL_TR_NUMBERS:
        if tok.startswith(word[0]):
            ending = re.fullmatch(CTL_TR_NUMBER_END, tok[len(word[0]):])
            if ending:
                return [word[1], word[2], 1 if ending.group(1) else 2]
    return None


def ctl_tr_word(tok, stems):
    """1-based position of the month or weekday this token names, with any case ending; 0 if none."""
    for index in range(len(stems)):
        forms = [stems[index]]
        if stems[index].endswith("k"):
            forms.append(stems[index][:-1] + "g")
        for form in forms:
            if tok == form or (tok.startswith(form) and re.fullmatch(CTL_TR_WORD_END, tok[len(form):])):
                return index + 1
    return 0


def ctl_turkish(said):
    """True when the words are Turkish: a Turkish letter, a word only Turkish has, or nothing but Turkish number
    words. 'on' and 'bin' alone decide nothing: they are English words too."""
    raw = str(said or "")
    for mark in CTL_TR_LETTERS:
        if mark in raw:
            return True
    words = re.findall(r"[a-z]+", ctl_fold(raw))
    every = len(words) > 0
    for tok in words:
        number = ctl_tr_number(tok)
        if tok in CTL_TR_SIGNS or tok in CTL_TR_MONTHS or tok in CTL_TR_DAYS or ctl_tr_word(tok, CTL_TR_LONG):
            return True
        if number and not number[2] and number[0] not in (10, 1000):
            return True
        if number and number[2] and number[0] in (0, 8, 9, 20, 60, 70, 80, 90):
            return True
        if not number:
            every = False
    return every


def ctl_said_parts(said):
    """The reply cut at its correction words (sorry, I mean, pardon, yani): the last part is what the caller
    settled on. One part when nothing was corrected."""
    raw = str(said or "")
    low = ctl_fold(raw)
    if len(low) != len(raw):
        raw = low
    parts = []
    start = 0
    for found in re.finditer(CTL_CORRECTIONS, low):
        parts.append(raw[start:found.start()])
        start = found.end()
    parts.append(raw[start:])
    kept = [part for part in parts if [ch for ch in part if ch.isalnum()]]
    return kept if kept else [raw]


def ctl_corrected(said):
    """True when the reply takes something back: it holds a correction word that is more than a filler."""
    for found in re.finditer(CTL_CORRECTIONS, ctl_fold(said)):
        if found.group(0) not in CTL_SOFT:
            return True
    return False


def ctl_word_number(tok, turkish, english=True):
    """[value, kind, has an ending] for a number word, English first, Turkish when the reply is Turkish; else None."""
    if english:
        if tok in CTL_UNITS:
            value = CTL_UNITS.index(tok)
            return [value, "unit" if value < 10 else "teen", False]
        if tok in CTL_TENS and not tok.endswith("ieth"):
            return [CTL_TENS[tok], "ten", False]
        if tok == "hundred":
            return [100, "hundred", False]
        if tok == "thousand":
            return [1000, "thousand", False]
        if tok == "million":
            return [1000000, "million", False]
    if turkish:
        return ctl_tr_number(tok)
    return None


def ctl_runs(tokens, turkish, english=True, numerals=False):
    """Number words read as numbers. Each run becomes [value, has an ending, tokens used]; every other token stays
    as it is. 'four hundred and sixty three' is one run, 'four sixty three' is two, and a zero always stands alone.
    With numerals, plain digits take part: '2 bin 500' is 2500."""
    out = []
    i = 0
    while i < len(tokens):
        total = 0
        current = 0
        j = i
        ended = False
        zero = False
        open_ten = False
        literal = False
        fresh = True
        thousands = False
        millions = False
        while j < len(tokens) and not ended and not zero:
            tok = tokens[j]
            if tok.isdigit():
                if not numerals or not fresh or (j > i and int(tok) >= 1000):
                    break
                current = int(tok)
                literal = True
                fresh = False
                j += 1
                continue
            number = ctl_word_number(tok, turkish, english)
            if number is None:
                # "four hundred and sixty": and joins only what a hundred or a thousand left open.
                following = ctl_word_number(tokens[j + 1], turkish, english) if j + 1 < len(tokens) and not tokens[j + 1].isdigit() else None
                if tok == "and" and english and j > i and current % 100 == 0 and (current or total) and following and following[1] in ("unit", "teen", "ten") and following[0]:
                    j += 1
                    continue
                break
            value = number[0]
            kind = number[1]
            if kind == "unit" and value == 0:
                if j > i:
                    break
                zero = True
            elif kind == "unit":
                if literal or not (current % 100 == 0 or open_ten):
                    break
                current += value
                open_ten = False
            elif kind == "teen" or kind == "ten":
                if literal or current % 100:
                    break
                current += value
                open_ten = kind == "ten"
            elif kind == "hundred":
                if current >= 100:
                    break
                current = (current or 1) * 100
                open_ten = False
                literal = False
            elif kind == "thousand":
                if thousands:
                    break
                total += (current or 1) * 1000
                current = 0
                thousands = True
                open_ten = False
                literal = False
            else:
                if thousands or millions:
                    break
                total += (current or 1) * 1000000
                current = 0
                millions = True
                open_ten = False
                literal = False
            fresh = current == 0 and not zero
            ended = number[2]
            j += 1
        if j > i:
            out.append([total + current, ended, j - i])
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return out


def ctl_tr(said, turkish=None):
    """A Turkish phrase about a day or a date, with its Turkish words put into the English ones ctl_day reads.
    Other words pass through. A phrase that is not Turkish is returned unchanged."""
    try:
        raw = str(said or "")
        if turkish is None:
            turkish = ctl_turkish(raw)
        if not turkish:
            return raw
        # 26'si, 26'sinda, 5'inde name a day of the month; 11'de and 5'e are times of day and stay plain numbers.
        marked = re.sub(r"([0-9]+)\s*'\s*(?:s?[iu]|[iu]?nc[iu])[a-z]*", r" ctlday \1 ", ctl_fold(raw))
        marked = re.sub(r"'[a-z]+", " ", marked)
        items = []
        for item in ctl_runs(re.findall(r"[a-z]+|[0-9]+", marked), True, False, False):
            items.append([int(item), False, 1] if isinstance(item, str) and item.isdigit() else item)
        out = []
        for pos in range(len(items)):
            item = items[pos]
            before = items[pos - 1] if pos else ""
            before2 = items[pos - 2] if pos > 1 else ""
            after = items[pos + 1] if pos + 1 < len(items) else ""
            after2 = items[pos + 2] if pos + 2 < len(items) else ""
            marked_day = before in ("ayin", "ayi", "ayinin", "ctlday")
            if isinstance(item, list):
                month_next = isinstance(after, str) and ctl_tr_word(after, CTL_TR_MONTHS) > 0
                if before == "saat":
                    out.append(str(item[0]))
                elif after in ("gun", "gunu", "gune") and after2 == "sonra":
                    out.append("in " + str(item[0]) + " days")
                elif after in ("hafta", "haftaya") and after2 == "sonra":
                    out.append("in " + str(item[0]) + " weeks")
                elif item[1] and item[0] in (1, 10, 1000) and not marked_day and not month_next:
                    # "onu", "ona", "biri", "bina" are everyday words too: alone they are never a day.
                    continue
                elif (item[1] == 1 or marked_day) and 1 <= item[0] <= 31:
                    out.append("the " + str(item[0]) + " th")
                else:
                    out.append(str(item[0]))
            elif item in ("ay", "ayin", "ayi", "ayinin", "ayinda", "ayina", "ctlday"):
                if before in ("gelecek", "onumuzdeki") and item != "ctlday":
                    out.append("next month")
            elif ctl_tr_word(item, CTL_TR_MONTHS):
                out.append(CTL_MONTHS[ctl_tr_word(item, CTL_TR_MONTHS) - 1])
            elif ctl_tr_word(item, CTL_TR_DAYS):
                name = CTL_TR_DAY_NAMES[ctl_tr_word(item, CTL_TR_DAYS) - 1]
                if before == "haftaya" or (before == "hafta" and before2 in ("gelecek", "onumuzdeki", "oburku")):
                    out.append(name + " next week")
                elif before == "bu" or (before == "hafta" and before2 == "bu"):
                    out.append("this " + name)
                elif before == "gelecek":
                    out.append("next " + name)
                else:
                    out.append(name)
            elif item.startswith("bugun") or item in ("simdi", "hemen"):
                out.append("today")
            elif (item == "yarindan" and after == "sonra") or (item == "obur" and after in ("gun", "gunu")):
                out.append("day after tomorrow")
            elif item.startswith("yarin"):
                if "day after tomorrow" not in out:
                    out.append("tomorrow")
            else:
                out.append(item)
        return " ".join(out)
    except Exception:
        return str(said or "")


def ctl_numeric_date(text, base=None):
    """A date given only as numbers, the last one said: 14.03.1988 or 14/03/1988, day first unless only the
    other order is a date. With the call's date also a day and a month alone (26.10), in the year that is ahead.
    '' if there is none."""
    said = str(text or "")
    full = re.findall(r"(?<![0-9.,/])([0-9]{1,2})[./]([0-9]{1,2})[./]([0-9]{4})(?![0-9])", said)
    short = []
    if not full and base is not None:
        for found in re.finditer(r"(?<![0-9.,/])([0-9]{1,2})([./])([0-9]{1,2})(?![0-9.,/])", said):
            rest = re.findall(r"[a-z]+", ctl_fold(said[found.end():]))
            # "5.10 dollars" is an amount, and with a dot "10.30" is a time: neither is turned round into a date.
            if not (rest and ctl_money_word(rest[0])):
                short.append([found.group(1), found.group(3), found.group(2)])
    if not full and not short:
        return ""
    last = full[-1] if full else short[-1]
    day = int(last[0])
    month = int(last[1])
    if month > 12 and day <= 12 and (full or last[2] == "/"):
        day, month = month, day
    built = ctl_build(int(last[2]) if full else base.year, month, day)
    if built and not full and built < base:
        built = ctl_build(base.year + 1, month, day)
    return built.isoformat() if built else ""


def ctl_digit_words(text, turkish):
    """The digits of one stretch of words, in order; '' when a word that is no digit is among them."""
    parts = []
    repeat = 1
    for item in ctl_runs(re.findall(r"[a-z]+|[0-9]+", ctl_fold(text)), turkish, True, False):
        if isinstance(item, list):
            piece = str(item[0])
        elif item.isdigit():
            piece = item
        elif item in ("double", "cift", "triple") and repeat == 1:
            repeat = 3 if item == "triple" else 2
            continue
        elif item in ("oh", "o") and not turkish:
            piece = "0"
        elif item in CTL_FILLERS and repeat == 1:
            continue
        else:
            return ""
        parts.append(piece * repeat)
        repeat = 1
    return "".join(parts) if repeat == 1 else ""


def ctl_money_word(tok):
    """'major' for a currency word, 'minor' for its hundredth, else ''."""
    if not isinstance(tok, str):
        return ""
    for stem in CTL_MINOR:
        if tok.startswith(stem):
            return "minor"
    for stem in CTL_MAJOR:
        if tok.startswith(stem):
            return "major"
    if tok == "kr":
        return "minor"
    return "major" if tok in ("tl", "usd", "eur", "gbp") else ""


def ctl_grouped(groups):
    """True for digits written in groups of three: 1 250, 12 500 000."""
    if not groups or not groups[0].isdigit() or len(groups[0]) > 3:
        return False
    for group in groups[1:]:
        if len(group) != 3 or not group.isdigit():
            return False
    return True


def ctl_chunk_cents(tok):
    """Hundredths for an amount written in digits: 1250, 1250.5, 1250,50, 1.250,50, 1,250.50, 1.250. None if it is none."""
    if tok.isdigit():
        return int(tok) * 100
    if "." in tok and "," in tok:
        # Both marks: the last one is the decimal mark, the other one groups the thousands.
        mark = "." if tok.rfind(".") > tok.rfind(",") else ","
        if tok.count(mark) != 1:
            return None
        head = tok.split(mark)[0]
        tail = tok.split(mark)[1]
        groups = head.split("," if mark == "." else ".")
        if not tail.isdigit() or len(tail) > 2 or not ctl_grouped(groups):
            return None
        return int("".join(groups)) * 100 + int((tail + "0")[:2])
    groups = tok.split("." if "." in tok else ",")
    # One mark: one or two digits after it are hundredths, three are thousands (money has no third decimal).
    if len(groups) == 2 and groups[0].isdigit() and groups[1].isdigit() and len(groups[1]) <= 2:
        return int(groups[0]) * 100 + int((groups[1] + "0")[:2])
    return int("".join(groups)) * 100 if ctl_grouped(groups) else None


def ctl_amount_cents(text, turkish):
    """Hundredths for the one amount these words hold, 0 when they hold none or more than one."""
    items = ctl_runs(re.findall(r"[a-z]+|[0-9][0-9.,]*[0-9]|[0-9]", ctl_fold(text)), turkish, True, True)
    found = []
    for pos in range(len(items)):
        item = items[pos]
        before = items[pos - 1] if pos else ""
        after = items[pos + 1] if pos + 1 < len(items) else ""
        lone = False
        daylike = False
        if isinstance(item, list):
            cents = item[0] * 100
            # "bir", "one", "onu", "bini" are everyday words, "beste" is a time of day and "yirmisinde" a day:
            # without a currency none of them is an amount.
            dated = item[0] <= 31 and bool(item[1] or after in ("st", "nd", "rd", "th")
                                           or (isinstance(after, str) and re.fullmatch(r"s?[iu](?:n?[dt][ae]n?|n?[ae]|n?[iu]n)?", after)))
            lone = (item[2] == 1 and item[0] == 1) or dated or bool(item[1] and item[0] == 1000)
            daylike = dated or (item[0] <= 31 and before in ("the", "ayin"))
        elif item[:1].isdigit():
            cents = ctl_chunk_cents(item)
            if cents is None:
                continue
        else:
            continue
        nxt = pos + 1
        if nxt < len(items) and items[nxt] == "bucuk":
            cents += 50
            nxt += 1
        kind = ctl_money_word(items[nxt]) if nxt < len(items) else ""
        found.append([cents, pos, daylike, lone, kind, nxt])
    majors = [f for f in found if f[4] == "major"]
    if len(majors) > 1:
        return 0
    if majors:
        main = majors[0]
    else:
        plain = [f for f in found if f[4] == "" and not f[3]]
        if len(plain) > 1:
            plain = [f for f in plain if not f[2]]
        if len(plain) != 1:
            # "elli kurus" alone is half a unit; anything else here is no amount or two.
            return found[0][0] // 100 if len(found) == 1 and found[0][4] == "minor" else 0
        main = plain[0]
    total = main[0]
    # The hundredths that follow the whole part: "540 lira 50 kurus", "dollars and fifty cents", "540 lira 50".
    k = main[5] + (1 if main[4] == "major" else 0)
    while k < len(items) and items[k] in ("and", "ve"):
        k += 1
    for f in found:
        small = f[0] // 100
        if f[1] == k and f[1] != main[1] and total % 100 == 0 and f[0] % 100 == 0 and small < 100:
            if f[4] == "minor" or (main[4] == "major" and f[4] == "" and not f[2] and f[5] >= len(items)):
                total += small
    return total


def ctl_amount(said):
    """An amount of money said in words or in digits, as text with two decimals ('1250.50'). '' when the words
    hold no single amount: a reference (the full amount, the minimum), two amounts, or a split that can be read
    two ways ('twelve fifty'). What follows the last correction word is read first."""
    try:
        if isinstance(said, (int, float)) and not isinstance(said, bool):
            cents = int(round(said * 100))
        else:
            whole = str(said or "")
            turkish = ctl_turkish(whole)
            parts = ctl_said_parts(whole)
            cents = 0
            for index in range(len(parts) - 1, -1, -1):
                cents = ctl_amount_cents(parts[index], turkish)
                if cents:
                    break
            if not cents and len(parts) > 1:
                cents = ctl_amount_cents(whole, turkish)
        if cents <= 0:
            return ""
        return str(cents // 100) + "." + ("0" + str(cents % 100))[-2:]
    except Exception:
        return ""


# One of several things. Words for every one of them, for the ones not named, and for a no.
CTL_ALL = (r"\b(?:all|both|everything|every one|each|hepsi(?:n[ie]|nin|nde)?|tumu(?:n[ue]|nun)?|ikisi(?:n[ie]|nin)?"
           r"|ucu(?:n[ue]|nun)?|her biri(?:n[ie])?)\b")
CTL_REST = (r"\b(?:the rest|the others?|other (?:two|three|ones?)|remaining ones?|digerleri(?:n[ie])?|digerini|gerisi(?:n[ie])?"
            r"|kalanlar[iu]?|geri kalan\w*)\b")
# English says no before the thing ("not the loan"), Turkish after it ("krediyi odemeyecegim", "kredi degil").
CTL_NOT_AFTER = r"\b(?:not|no|never|neither|nor|without|except)\b"
CTL_NOT_BEFORE = (r"\b(?:degil|haric|disinda|haricinde|\w+m[ae]y[ae]c[ae]\w*|\w+m[iu]yor\w*|\w{2,}[ae]m[ae]m|\w+m[ae]y[iu]z"
                  r"|istemem|vermem|yapmam|yatirmam)\b")
CTL_LEAVE_OUT = r"\b(?:except|haric|disinda|haricinde)\b"
CTL_NONE = r"\b(?:none|neither|hicbiri\w*)\b"
# A yes said with a verb ends the reach of a no in a reply without punctuation.
CTL_WILL = (r"\b(?:i will|i can|i would|i could|i am going to|i want to|i pay|let me|\w+[ae]c[ae]g[iu]m|\w+[iu]yorum"
            r"|\w+[ae]bilirim|\w{2,}[aeiu]rim|\w+[ae]c[ae]g[iu]z)\b")
# "all" that is about an amount or about nothing: no choice of things.
CTL_NO_CHOICE = (r"\b(?:it all|all of (?:it|that)|at all|all right|after all|that is all|that all|thats all|is all|first of all"
                 r"|above all|all the time|all day)\b")
CTL_TAKE_BACK = (r"\b(?:no wait|wait no|i mean|i meant|scratch that|make that|ozur dilerim|daha dogrusu|sorry|correction|pardon"
                 r"|duzeltiyorum|duzelteyim|yanlis|affedersiniz)\b")
CTL_NAME_FILL = ["the", "a", "an", "my", "your", "our", "this", "that", "of", "for", "ending", "in", "with", "number", "one",
                 "and", "or", "ile", "biten", "sonu", "son", "hane", "haneli", "numarali", "nolu", "olan", "ve", "veya"]
CTL_ORDER = [r"first one|ilki\w*|birincisi\w*", r"second one|ikincisi\w*", r"third one|ucuncusu\w*",
             r"fourth one|dorduncusu\w*", r"fifth one|besincisi\w*"]
CTL_LAST = r"last one|sonuncu\w*"


def ctl_name_tokens(name):
    """The words of a name that tell it apart: plain lower-case words and numbers, without the filler words."""
    found = re.findall(r"[a-z]+|[0-9]+", ctl_fold(name).replace("_", " "))
    return [tok for tok in found if tok not in CTL_NAME_FILL]


def ctl_same_word(said, name, turkish):
    """True when a word the caller said is the word of a name: the same word, an English plural, or in Turkish
    the same stem under another ending (karti, kartimi, kartin)."""
    if said == name:
        return True
    if said.isdigit() or name.isdigit():
        return False
    if said in (name + "s", name + "es") or name == said + "s":
        return True
    short = min(len(said), len(name))
    if not turkish or short < 4:
        return False
    same = 0
    while same < short and said[same] == name[same]:
        same += 1
    return same >= max(4, short - 2) and max(len(said), len(name)) - same <= 5


def ctl_said_no(at, after, before, will):
    """True when the word at this place in a clause is said with a no: an English no before it, or a Turkish
    one after it, with no new yes in between."""
    for start in after:
        if start < at and not [w for w in will if start < w < at]:
            return True
    later = [start for start in before if start > at]
    if later and not [w for w in will if at < w < min(later)]:
        return True
    return False


def ctl_choice_read(text, names, turkish):
    """Which of the names the words choose, decline or leave unclear: three lists of positions."""
    count = len(names)
    text = re.sub(CTL_NO_CHOICE, " ", text)
    text = re.sub(r"\b(all|everything|both)\s+but\b", r"\1 except", text)
    text = re.sub(r"^\s*(?:(?:no|hayir|yok|yes|yeah|evet|ok|okay|tamam|well|peki)\b[\s,.!]*)+", "", text)
    state = dict()
    unclear = []
    rest = 0
    for clause in re.split(r"[.;,!?]|\b(?:but|however|though|ama|fakat|ancak|yalniz)\b", text):
        words = re.findall(r"[a-z]+|[0-9]+", clause)
        if not words:
            continue
        if words in (["no"], ["hayir"], ["yok"]):
            # A bare no after something was named takes it back: "the card, no, the loan".
            for key in list(state):
                if state[key] == 1:
                    del state[key]
            continue
        joined = " " + " ".join(words) + " "
        offsets = []
        at = 1
        for word in words:
            offsets.append(at)
            at += len(word) + 1
        after = [found.start() for found in re.finditer(CTL_NOT_AFTER, joined)]
        before = [found.start() for found in re.finditer(CTL_NOT_BEFORE, joined)]
        will = [found.start() for found in re.finditer(CTL_WILL, joined) if found.start() not in before]
        if words[-1] in ("no", "not") and len(words) > 1:
            # "the rest no": a no at the end is about the whole clause.
            after = [0]
            will = []
        named = dict()
        loose = []
        used = []
        for index in range(len(words)):
            word = words[index]
            holders = [i for i in range(count) if word in names[i]]
            if not holders:
                holders = [i for i in range(count) if [tok for tok in names[i] if ctl_same_word(word, tok, turkish)]]
            if not holders:
                continue
            used.append(index)
            if len(holders) == 1:
                if holders[0] not in named:
                    named[holders[0]] = offsets[index]
            else:
                loose.append([offsets[index], holders])
        for rank in range(len(CTL_ORDER) + 1):
            place = rank if rank < len(CTL_ORDER) else count - 1
            found = re.search(r"\b(?:" + (CTL_ORDER[rank] if rank < len(CTL_ORDER) else CTL_LAST) + r")\b", joined)
            if found and place < count and place not in named:
                named[place] = found.start()
        if not named:
            # A number of a name said in words: "the one ending nine zero one five".
            left = " ".join([words[i] for i in range(len(words)) if i not in used and (words[i] == "one" or words[i] not in CTL_NAME_FILL)])
            digits = ctl_digit_words(left, turkish) if left else ""
            if len(digits) >= 2:
                holders = [i for i in range(count) if [tok for tok in names[i] if tok.isdigit() and (tok.endswith(digits) or digits.endswith(tok))]]
                if len(holders) == 1:
                    named[holders[0]] = offsets[0]
        every = re.search(CTL_ALL, joined)
        nothing = re.search(CTL_NONE, joined)
        some = re.search(r"\bany\b", joined)
        if not every and nothing:
            every = nothing
        elif not every and some and ctl_said_no(some.start(), after, before, will):
            every = some
        grouped = False
        for item in loose:
            if [i for i in item[1] if i in named]:
                continue
            if every:
                # "both loans": every one that has this word.
                grouped = True
                for i in item[1]:
                    state[i] = -1 if nothing or ctl_said_no(item[0], after, before, will) else 1
            else:
                for i in item[1]:
                    if i not in unclear:
                        unclear.append(i)
        for i in named:
            state[i] = -1 if ctl_said_no(named[i], after, before, will) else 1
        if every and not grouped and (not named or re.search(CTL_LEAVE_OUT, joined)):
            value = -1 if nothing or ctl_said_no(every.start(), after, before, will) else 1
            for i in range(count):
                if i not in named:
                    state[i] = value
        others = re.search(CTL_REST, joined)
        if others:
            rest = -1 if ctl_said_no(others.start(), after, before, will) else 1
    for i in range(count):
        if rest and i not in state and i not in unclear:
            state[i] = rest
    return [[i for i in range(count) if state.get(i) == 1], [i for i in range(count) if state.get(i) == -1],
            [i for i in range(count) if i in unclear and i not in state]]


def ctl_choice(said, options):
    """Which of several known things the caller's words name. options has one entry for each thing, in a fixed
    order: its name as the agent says it, or a list of its names (its type, its label, its card ending).
    Returns a dict. chosen, declined and unclear are lists of positions in options: what the caller picks,
    what the caller says no to in the same reply, and what one unclear mention could mean ("the loan" with two
    loans). kind is one, several, all, declined (only a no), unclear or none (nothing named).
    Reads "all three", "both", "both loans", "the first one", "the card ending 9015", "everything except the
    car loan", "the card yes, the rest no", and the Turkish forms. What follows a correction is read first."""
    result = dict(kind="none", chosen=[], declined=[], unclear=[])
    try:
        names = []
        labels = []
        for option in list(options or []):
            tokens = []
            for alias in (option if isinstance(option, (list, tuple)) else [option]):
                labels.append(str(alias))
                for tok in ctl_name_tokens(alias):
                    if tok not in tokens:
                        tokens.append(tok)
            names.append(tokens)
        if not names:
            return result
        whole = str(said or "")
        turkish = ctl_turkish(whole) or ctl_turkish(" ".join(labels))
        text = ctl_fold(whole).replace("n't", " not").replace("cannot", "can not")
        text = re.sub(r"'\w*", " ", text)
        cut = -1
        for found in re.finditer(CTL_TAKE_BACK, text):
            cut = found.end()
        read = ctl_choice_read(text[cut:], names, turkish) if cut >= 0 else [[], [], []]
        if not (read[0] or read[1] or read[2]):
            read = ctl_choice_read(text, names, turkish)
        result["chosen"] = read[0]
        result["declined"] = read[1]
        result["unclear"] = read[2]
        if read[2]:
            result["kind"] = "unclear"
        elif read[0]:
            result["kind"] = "all" if len(read[0]) == len(names) and len(names) > 1 else ("one" if len(read[0]) == 1 else "several")
        elif read[1]:
            result["kind"] = "declined"
    except Exception:
        pass
    return result
'''

DATE_HELPERS += SPEECH_HELPERS

HUMAN_HELPERS = r'''
# Text speech state; callers supply completeness/provenance and policy themselves.
import json


def ctl_digits(said, count=0):
    """Digits in order, zeros kept, however they were said: one by one ('zero three five eight',
    'dort dort yedi bir'), in groups ('forty-four seventy-one', 'kirk dort yetmis bir', 'four sixty three'),
    as numerals ('463'), or doubled ('double four', 'cift sifir').
    '' when any other word is among them: a wrong security answer costs an attempt, asking again does not.
    What follows the last correction word is read first. With count, the last count digits when more were
    said: a whole number given for 'the last four', or a second answer that follows a first one."""
    try:
        whole = str(said or '')
        turkish = ctl_turkish(whole)
        parts = ctl_said_parts(whole)
        digits = ''
        for index in range(len(parts) - 1, -1, -1):
            digits = ctl_digit_words(parts[index], turkish)
            if digits:
                break
    except Exception:
        digits = ''
    try:
        wanted = int(count or 0)
    except Exception:
        wanted = 0
    return digits[-wanted:] if 0 < wanted < len(digits) else digits


def ctl_collect(values, name, said, count):
    """A number the caller may give in parts: '463', then '51'. Call it once for each reply, with the words of
    that reply only. Returns the whole number once count digits are there, else ''.
    It sets <name> (the number, or ''), <name>_complete (yes or no), <name>_parts (the digits kept so far) and
    <name>_heard (no when this reply held no digits: a question or a hold, which leaves the kept part as it is).
    A whole number, or a correction that does not complete the kept part, replaces that part."""
    try:
        wanted = int(count or 0)
    except Exception:
        wanted = 0
    try:
        whole = str(said or '')
        new = ctl_digits(whole)
        kept = str(values.get(name + '_parts') or '')
        done = str(values.get(name) or '') if values.get(name + '_complete') == 'yes' else ''
        values[name + '_heard'] = 'yes' if new else 'no'
        if new:
            joined = kept + new
            if wanted <= 0:
                done, kept = new, ''
            elif len(new) >= wanted:
                done, kept = new[-wanted:], ''
            elif len(joined) == wanted:
                done, kept = joined, ''
            elif len(joined) < wanted and not ctl_corrected(whole):
                done, kept = '', joined
            else:
                done, kept = '', new
        values[name + '_parts'] = kept
        values[name + '_complete'] = 'yes' if done else 'no'
        values[name] = done
        return done
    except Exception:
        values[name + '_complete'] = 'no'
        values[name] = ''
        return ''


def ctl_identity_date(said):
    """Identity has no default: the words must state one day, one month and one year, or the result is ''.
    When an earlier answer is still in front of a later one (a wrong date, then another; a correction),
    the latest complete date is the answer."""
    try:
        text = str(said or '').lower()
        exact = re.findall(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', text)
        if exact:
            return datetime.date.fromisoformat(exact[-1]).isoformat()
        numeric = ctl_numeric_date(text)
        if numeric:
            return numeric
        text = str(ctl_tr(said) or '').lower()
        tokens = re.findall(r'[a-z]+|[0-9]+', text)[-60:]
        for start in range(len(tokens)):
            part = tokens[start:]
            months = [i for i, t in enumerate(part) if ctl_month(t)]
            if len(months) != 1:
                continue
            spans = ctl_year_spans(part, ctl_numbers(part), months[0])
            if len(set(span[0] for span in spans)) != 1:
                continue
            # Words cut off at the front may leave the year of the earlier answer standing before a
            # later day and month: only a year said after the month belongs to this date.
            late = [span for span in spans if span[1] > months[0]]
            if start and not late:
                continue
            span = late[0] if late else spans[0]
            # The day is read from the words outside the year: "March nineteen eighty eight" names none.
            rest = part[:span[1]] + part[span[2]:]
            found = ctl_date(' '.join(rest) + ' ' + str(span[0]), str(span[0]) + '-01-01')
            # Read against a date that is not the call's: a day that stands apart from its month must not fall into another month.
            if found and int(found[5:7]) == ctl_month(part[months[0]]):
                return found
        return ctl_number_date(said)
    except Exception:
        return ''


def ctl_number_date(said):
    """A date said only as numbers, day then month then year: '14 3 1988', 'fourteen three nineteen eighty eight',
    'on dort uc bin dokuz yuz seksen sekiz'. '' unless the words are those numbers and nothing else."""
    values = []
    for item in ctl_runs(re.findall(r"[a-z]+|[0-9]+|,", ctl_fold(said)), ctl_turkish(said), True, True):
        if isinstance(item, list):
            values.append(item[0])
        elif item != ',' and item not in CTL_FILLERS:
            return ''
    if len(values) == 4 and values[2] in (19, 20) and values[3] <= 99:
        values = [values[0], values[1], values[2] * 100 + values[3]]
    if len(values) == 2 and values[1] % 1000 >= 900 and 1 <= values[1] // 1000 <= 12:
        # "uc bin dokuz yuz seksen sekiz": the month ran into the thousand of the year.
        values = [values[0], values[1] // 1000, 1000 + values[1] % 1000]
    if len(values) != 3 or not 1900 <= values[2] <= 2100:
        return ''
    day = values[0]
    month = values[1]
    if month > 12 and day <= 12:
        day, month = month, day
    built = ctl_build(values[2], month, day)
    return built.isoformat() if built else ''


def ctl_slot(values, name, value, raw, complete, turn, correction=False):
    """Incomplete/revised speech clears the routable value, retains raw provenance."""
    values[name + '_raw'] = str(raw or '')
    values[name + '_turn'] = str(turn)
    values[name + '_complete'] = 'yes' if complete and value not in (None, '') else 'no'
    if correction:
        values[name + '_revision'] = str(int(values.get(name + '_revision', '0')) + 1)
    # Assigned, never removed: only what a snippet assigns reaches the platform, so a removed key
    # would leave the earlier complete value routable. '' is "not given" throughout these rules.
    values[name] = str(value) if values[name + '_complete'] == 'yes' else ''
    return values[name + '_complete'] == 'yes'


def ctl_cents(amount):
    """Canonical numeric money only; ambiguous words are clarified by extraction."""
    text = str(amount).strip()
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', text):
        return ''
    parts = text.split('.')
    cents = int(parts[0]) * 100 + int((parts[1] if len(parts) > 1 else '').ljust(2, '0'))
    return str(cents) if cents > 0 else ''


def ctl_records(values):
    """The saved proposals; {} when the state is missing or damaged, so damage never counts as consent."""
    try:
        records = json.loads(values.get('ctl_proposals') or '{}')
        return dict((key, record) for key, record in records.items() if isinstance(record, dict))
    except Exception:
        return {}


def ctl_proposal(values, product, amount, day):
    """Each changed tuple creates a revision and invalidates only its own consent."""
    try:
        records = ctl_records(values)
        cents = ctl_cents(amount)
        parsed = datetime.date.fromisoformat(str(day)).isoformat()
        if not cents or not product:
            ctl_invalidate(values, product)
            return ''
        old = records.get(product, {})
        if old.get('cents') != cents or old.get('date') != parsed:
            records[product] = {'cents':cents, 'date':parsed, 'revision':old.get('revision', 0)+1, 'agreed':0}
        values['ctl_proposals'] = json.dumps(records)
        return str(records[product]['revision'])
    except Exception:
        # A malformed correction must not leave old consent usable.
        ctl_invalidate(values, product)
        return ''


def ctl_invalidate(values, product):
    try:
        records = ctl_records(values)
        if isinstance(records.get(product), dict):
            records[product]['agreed'] = 0
        values['ctl_proposals'] = json.dumps(records)
    except Exception:
        values['ctl_proposals'] = '{}'


def ctl_consent(values, product, revision, explicit):
    try:
        records = ctl_records(values)
        proposal = records.get(product, {})
        matched = explicit is True and bool(proposal.get('revision')) and str(proposal['revision']) == str(revision)
        if matched:
            proposal['agreed'] = proposal['revision']
            values['ctl_proposals'] = json.dumps(records)
        return matched
    except Exception:
        return False


def ctl_write_ready(values, product, amount, day):
    try:
        proposal = ctl_records(values).get(product, {})
        return bool(proposal.get('revision') and proposal.get('agreed') == proposal.get('revision')
                    and proposal.get('cents') == ctl_cents(amount) and proposal.get('date') == str(day))
    except Exception:
        return False
'''

DATE_HELPERS += HUMAN_HELPERS

DATE_APPLY = '''
try:
    for ctlv_name in %s:
        ctlv_raw = vars.get(ctlv_name)
        if not isinstance(ctlv_raw, str) or not ctlv_raw.strip() or ctlv_raw == vars.get(ctlv_name + "_iso"):
            continue
        ctlv_day = ctl_date(ctlv_raw, vars.get("now"))
        vars[ctlv_name + "_said"] = ctlv_raw
        vars[ctlv_name + "_iso"] = ctlv_day
        vars[ctlv_name] = ctlv_day
except Exception:
    pass
'''

# The same for an amount: the words become '1250.50', or '' when they hold no single amount.
AMOUNT_APPLY = '''
try:
    for ctlv_name in %s:
        ctlv_raw = vars.get(ctlv_name)
        if not isinstance(ctlv_raw, str) or not ctlv_raw.strip() or ctlv_raw == vars.get(ctlv_name + "_num"):
            continue
        ctlv_sum = ctl_amount(ctlv_raw)
        vars[ctlv_name + "_said"] = ctlv_raw
        vars[ctlv_name + "_num"] = ctlv_sum
        vars[ctlv_name] = ctlv_sum
except Exception:
    pass
'''

STRUCTURED_APPLY = '''
import json
try:
    for ctlv_name, ctlv_field in %s:
        ctlv_cur = vars.get(ctlv_name)
        if isinstance(ctlv_cur, (list, dict)) and ctlv_cur:
            continue
        if isinstance(ctlv_cur, str) and ctlv_cur.strip()[:1] in ("[", "{"):
            continue
        ctlv_saved = vars.get(ctlv_name + "_json")
        if isinstance(ctlv_saved, str) and ctlv_saved.strip()[:1] in ("[", "{"):
            vars[ctlv_name] = ctlv_saved
            continue
        ctlv_rows = {}
        ctlv_mark = "_response.data." + ctlv_field + "."
        for ctlv_key in list(vars.keys()):
            ctlv_text = str(ctlv_key)
            if ctlv_mark not in ctlv_text:
                continue
            ctlv_rest = ctlv_text.split(ctlv_mark, 1)[1].split(".")
            if len(ctlv_rest) == 2 and ctlv_rest[0].isdigit():
                ctlv_rows.setdefault(int(ctlv_rest[0]), {})[ctlv_rest[1]] = vars[ctlv_key]
        if ctlv_rows:
            vars[ctlv_name] = json.dumps([ctlv_rows[ctlv_i] for ctlv_i in sorted(ctlv_rows)])
except Exception:
    pass
'''

STRUCTURED_HOOK = '''
import json
try:
    if isinstance(result, dict) and isinstance(result.get("data"), dict):
        for ctlv_name, ctlv_field in %s:
            ctlv_at = result["data"]
            for ctlv_part in ctlv_field.split("."):
                ctlv_at = ctlv_at.get(ctlv_part) if isinstance(ctlv_at, dict) else None
            if isinstance(ctlv_at, (list, dict)):
                vars[ctlv_name] = json.dumps(ctlv_at)
                vars[ctlv_name + "_json"] = vars[ctlv_name]
except Exception:
    pass
'''


GUARD = "controller loop guard: this stage was re-entered too often, leave through its closing route"


def guard_loops(workflow):
    """End a stuck conversation stage through its own closing route.

    max_node_turns counts one visit only, so a stage that keeps being re-entered (a route that
    bounces back to it) never reaches its cap. The platform also counts turns over the whole call;
    twice the per-visit cap there can only mean a loop."""
    nodes = workflow.get("nodes") or {}
    for key, node in nodes.items():
        if not isinstance(node, dict) or node.get("node_type") != "conversation" or not isinstance(node.get("transitions"), list):
            continue
        node["transitions"] = [t for t in node["transitions"] if not (isinstance(t, dict) and t.get("description") == GUARD)]
        target = node.get("max_turn_transition")
        if target not in nodes or target == key:
            continue
        cap = node.get("max_node_turns")
        limit = max(2 * cap if isinstance(cap, int) and cap > 0 else 20, 8)
        node["transitions"].insert(0, {"target_node": target, "description": GUARD,
                                       "condition": {"variable": key + ".total_turns", "operator": "greater_than", "operand": limit}})
    return workflow


def nested_values(contract, values):
    """Field values placed where the documented request has them."""
    shaped = {}
    for name, path in contract["nest"].items():
        if name in values:
            at = shaped
            for part in path[:-1]:
                at = at.setdefault(part, {})
            at[path[-1]] = values[name]
    return shaped


def bound_fields(contract, body):
    """What each field of a compiled tool's request is bound to, for either shape of request: {field: default}."""
    if not contract.get("nest"):
        return {field: prop["default"] for field, prop in (body.get("properties") or {}).items() if isinstance(prop, dict) and "default" in prop}
    found = {}
    for name, path in contract["nest"].items():
        at = body.get("default")
        for part in path:
            at = at.get(part) if isinstance(at, dict) else None
        if at is not None:
            found[name] = at
    return found


def strip(code):
    """Remove a previously compiled prelude so recompiling a workflow never stacks them."""
    code = str(code or "")
    while START in code and END in code:
        head, rest = code.split(START, 1)
        code = head + rest.split(END, 1)[1].lstrip("\n")
    return code


def wrap(body, code):
    return START + "\n" + body.strip("\n") + "\n" + END + "\n" + strip(code)


def _helper_items():
    """The helper source cut into its top-level pieces: (names it defines, its text, names it uses)."""
    lines = DATE_HELPERS.splitlines()
    items = []
    for node in ast.parse(DATE_HELPERS).body:
        # Without the docstring and the comment lines: this text is copied into many stages, and they are read here.
        doc = node.body[0] if isinstance(node, ast.FunctionDef) and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) else None
        skipped = range(doc.lineno, doc.end_lineno + 1) if doc and len(node.body) > 1 else ()
        text = "\n".join(line for number, line in enumerate(lines[node.lineno - 1:node.end_lineno], node.lineno)
                         if number not in skipped and not line.strip().startswith("#"))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            items.append((None, text, set()))
            continue
        defined = {node.name} if isinstance(node, ast.FunctionDef) else {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)}
        items.append((defined, text, {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}))
    return items


HELPER_ITEMS = _helper_items()


def helpers_for(names):
    """The source of the named helpers with everything they call, and nothing else: the compiled agent
    is one request, and the whole helper block in each of forty code stages was three quarters of it."""
    known = set().union(*(defined for defined, _, _ in HELPER_ITEMS if defined))
    wanted, grown = set(names) & known, True
    while grown:
        grown = False
        for defined, _, used in HELPER_ITEMS:
            if defined and defined & wanted and not (used & known) <= wanted:
                wanted |= used & known
                grown = True
    if not wanted:
        return ""
    return "\n" + "\n\n".join(text for defined, text, _ in HELPER_ITEMS if defined is None or defined & wanted) + "\n"


def _first_code_after(named, everywhere, sources):
    """The code stages that are the first to run after one of the source stages: reached from it without
    passing another code stage. A caller's words extracted in a source are converted there, once."""
    found, seen, queue = set(), set(), list(sources)
    while queue:
        node = named[queue.pop()]
        targets = [t.get("target_node") for t in node["transitions"] if isinstance(t, dict)] if isinstance(node.get("transitions"), list) else []
        for target in targets + [node.get("max_turn_transition"), node.get("passthrough_default_transition")] + everywhere:
            if not isinstance(target, str) or target not in named or target in seen:
                continue
            seen.add(target)
            if named[target].get("node_type") == "code":
                found.add(target)
            else:
                queue.append(target)
    return found


def apply(workflow, contracts):
    """Rewrite day and amount extraction to spoken words and compile the helpers into the code stages and tool hooks that need them."""
    named = {key: n for group in ("nodes", "global_nodes") for key, n in (workflow.get(group) or {}).items() if isinstance(n, dict)}
    every = list(named.values())
    rows = lambda value: [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    dates, amounts = [], []
    sources = {"date": set(), "amount": set()}
    for key, node in named.items():
        for item in rows(node.get("extraction_schema")):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            description = str(item.get("description", ""))
            if item.get("type") in ("date", "datetime") or SAID in description:
                item["type"] = "string"
                if SAID not in description:
                    item["description"] = (description.strip() + " " + SAID).strip()
                if SINGLE_DAY not in item["description"]:
                    item["description"] += " " + SINGLE_DAY
                if item["name"] not in dates:
                    dates.append(item["name"])
                sources["date"].add(key)
            elif item.get("type") in ("amount", "money") or SAID_AMOUNT in description:
                item["type"] = "string"
                if SAID_AMOUNT not in description:
                    item["description"] = (description.strip() + " " + SAID_AMOUNT).strip()
                if ONE_AMOUNT not in item["description"]:
                    item["description"] += " " + ONE_AMOUNT
                if item["name"] not in amounts:
                    amounts.append(item["name"])
                sources["amount"].add(key)
    # An interrupt handler can follow any stage.
    everywhere = [key for key in (workflow.get("global_nodes") or {}) if key in named]
    first = {kind: _first_code_after(named, everywhere, keys) for kind, keys in sources.items()}
    structured = []
    for node in every:
        for placement in ("tools", "pre_actions"):
            for tool in rows(node.get(placement)):
                function = tool.get("function") if isinstance(tool, dict) else None
                if not isinstance(function, dict) or function.get("handler") != "__function__:api_call":
                    continue
                contract = contracts["operations"].get(function.get("name"))
                if not contract:
                    continue
                schema = contract["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})

                def kind(field):
                    # The type of a result field, also of one inside an object of the result (data.cards).
                    at = schema
                    for part in field.split("."):
                        at = (at.get("properties") or {}).get(part, {}) if isinstance(at, dict) else {}
                    return at.get("type") if isinstance(at, dict) else None
                mappings = tool.get("response_mapping") if placement == "tools" else node.get("response_mapping")
                pairs = []
                for mapping in rows(mappings):
                    path, variable = str(mapping.get("path", "")), mapping.get("variable")
                    field = path[len("data."):]
                    if path.startswith("data.") and field and variable and kind(field) in ("array", "object"):
                        pairs.append([variable, field])
                structured += [p for p in pairs if p not in structured]
                # A hook is its own sandbox too: it carries the helpers it calls, like a code stage.
                called = lambda code: helpers_for(set(re.findall(r"\b(?:ctl|CTL)_\w+", code)))
                post = strip(tool.get("post_process_code")).rstrip()
                if pairs or called(post):
                    tool["post_process_code"] = ((wrap(called(post), "") if called(post) else "") + (post + "\n" if post else "")
                                                 + (START + "\n" + (STRUCTURED_HOOK % json.dumps(pairs)).strip("\n") + "\n" + END + "\n" if pairs else ""))
                elif post != str(tool.get("post_process_code") or "").rstrip():
                    tool["post_process_code"] = post
                # A day or an amount bound straight into a request must be converted before the request is built.
                body = json.dumps(function.get("parameters", {}).get("properties", {}).get("body", {}))
                bound = lambda names: [name for name in names if "{{" + name + "}}" in body]
                pre = strip(tool.get("pre_process_code"))
                blocks = (DATE_APPLY % json.dumps(bound(dates)) if bound(dates) else "") + (AMOUNT_APPLY % json.dumps(bound(amounts)) if bound(amounts) else "")
                if blocks or called(pre):
                    tool["pre_process_code"] = wrap(called(pre + blocks) + blocks, pre)
                elif pre != str(tool.get("pre_process_code") or ""):
                    tool["pre_process_code"] = pre
    for key, node in named.items():
        if node.get("node_type") != "code":
            continue
        for tool in rows(node.get("pre_actions")):
            code = tool.get("function", {}).get("parameters", {}).get("properties", {}).get("code", {}) if isinstance(tool.get("function"), dict) else {}
            if not isinstance(code, dict) or not isinstance(code.get("default"), str):
                continue
            own = strip(code["default"])
            # A stage is its own sandbox, so the helpers travel with it: those it calls, and the conversion of
            # what the caller said in the first code stage after the words were extracted.
            blocks = ((DATE_APPLY % json.dumps(dates) if dates and key in first["date"] else "")
                      + (AMOUNT_APPLY % json.dumps(amounts) if amounts and key in first["amount"] else ""))
            parts = helpers_for(set(re.findall(r"\b(?:ctl|CTL)_\w+", own + blocks))) + blocks + (STRUCTURED_APPLY % json.dumps(structured) if structured else "")
            code["default"] = wrap(parts, own) if parts else own
    return guard_loops(workflow)
