"""Controller-owned runtime support compiled into every workflow.

Nothing here comes from a brief. It encodes observed platform behaviour and plain English calendar
language, so that model-written policy code receives usable values:

- response_mapping stores scalars only; a mapped list/object must be materialised for code nodes.
- Business-day arithmetic written by a model has been wrong often enough that it is provided here;
  the weekdays and excluded dates are always arguments the generated code takes from its source.
- The platform resolves a `date` extraction against the real clock, not the call's `now` variable,
  so "tomorrow" lands on the wrong day whenever a call is simulated on another date. Spoken dates
  are therefore captured as the customer's words and resolved here against `now`.
"""
import json

START = "# controller: runtime prelude"
END = "# controller: end of runtime prelude"
SAID = ("If the customer states a complete calendar date including its year, give it as YYYY-MM-DD. Otherwise give the customer's own final "
        "words for the day exactly as said (for example: tomorrow, this Friday, the 26th, 6 November) and do not work out a calendar date yourself.")
# Words are captured, so without this a period would count as a given day in every `is_set` route.
SINGLE_DAY = ("Extract only the date for the current requested slot; ignore dates of appointments, other products or unrelated stories. A correction replaces the previous date. Fill this only when the words name one single day. A period or a condition (for example: next week, the week after next, "
              "end of the month, in a few days, when my salary comes) is not a day: leave this variable out entirely.")

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
    """Resolve a spoken day against the call date. Returns YYYY-MM-DD, or '' when no single day is named."""
    try:
        base = datetime.date.fromisoformat(str(call_now)[:10])
        text = str(said or "").lower()
        iso = re.search(r"(\\d{4})-(\\d{2})-(\\d{2})", text)
        if iso:
            exact = ctl_build(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return exact.isoformat() if exact else ""
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
    except Exception:
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

HUMAN_HELPERS = r'''
# Text speech state; callers supply completeness/provenance and policy themselves.
import json


def ctl_digits(said, count=0):
    """Digits said one by one, in order, zeros kept ('zero three five eight', 'double four seven one').
    '' when any other word is among them: a wrong security answer costs an attempt, asking again does not.
    With count, the last count digits when more were said: a whole number given for 'the last four',
    or a second answer that follows a first one in the same words."""
    tokens = re.findall(r'[a-z]+|[0-9]+', str(said or '').lower())
    parts = []
    repeat = 1
    for token in tokens:
        if token in ('double', 'triple') and repeat == 1:
            repeat = 2 if token == 'double' else 3
            continue
        if token.isdigit():
            digit = token
        elif token in CTL_UNITS[:10]:
            digit = str(CTL_UNITS.index(token))
        elif token in ('oh', 'o'):
            digit = '0'
        elif token == 'and' and repeat == 1:
            continue
        else:
            return ''
        parts.append(digit * repeat)
        repeat = 1
    digits = ''.join(parts) if repeat == 1 else ''
    try:
        wanted = int(count or 0)
    except Exception:
        wanted = 0
    return digits[-wanted:] if 0 < wanted < len(digits) else digits


def ctl_identity_date(said):
    """Identity has no default: the words must state one day, one month and one year, or the result is ''.
    When an earlier answer is still in front of a later one (a wrong date, then another; a correction),
    the latest complete date is the answer."""
    try:
        text = str(said or '').lower()
        exact = re.findall(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', text)
        if exact:
            return datetime.date.fromisoformat(exact[-1]).isoformat()
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
            if found:
                return found
        return ''
    except Exception:
        return ''


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
            if isinstance(result["data"].get(ctlv_field), (list, dict)):
                vars[ctlv_name] = json.dumps(result["data"][ctlv_field])
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


def strip(code):
    """Remove a previously compiled prelude so recompiling a workflow never stacks them."""
    code = str(code or "")
    while START in code and END in code:
        head, rest = code.split(START, 1)
        code = head + rest.split(END, 1)[1].lstrip("\n")
    return code


def wrap(body, code):
    return START + "\n" + body.strip("\n") + "\n" + END + "\n" + strip(code)


def apply(workflow, contracts):
    """Rewrite date extraction to spoken words and compile the prelude into code nodes and tool hooks."""
    every = [n for group in ("nodes", "global_nodes") for n in (workflow.get(group) or {}).values() if isinstance(n, dict)]
    rows = lambda value: [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    dates = []
    for node in every:
        for item in rows(node.get("extraction_schema")):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            if item.get("type") in ("date", "datetime") or SAID in str(item.get("description", "")):
                item["type"] = "string"
                if SAID not in str(item.get("description", "")):
                    item["description"] = (str(item.get("description", "")).strip() + " " + SAID).strip()
                if SINGLE_DAY not in item["description"]:
                    item["description"] += " " + SINGLE_DAY
                if item["name"] not in dates:
                    dates.append(item["name"])
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
                schema = contract["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("properties", {})
                mappings = tool.get("response_mapping") if placement == "tools" else node.get("response_mapping")
                pairs = []
                for mapping in rows(mappings):
                    path, variable = str(mapping.get("path", "")), mapping.get("variable")
                    field = path[len("data."):]
                    if path.startswith("data.") and "." not in field and variable and schema.get(field, {}).get("type") in ("array", "object"):
                        pairs.append([variable, field])
                structured += [p for p in pairs if p not in structured]
                post = strip(tool.get("post_process_code")).rstrip()
                if pairs:
                    tool["post_process_code"] = (post + "\n" if post else "") + START + "\n" + (STRUCTURED_HOOK % json.dumps(pairs)).strip("\n") + "\n" + END + "\n"
                elif post != str(tool.get("post_process_code") or "").rstrip():
                    tool["post_process_code"] = post
                # A date bound straight into a request must be resolved before the request is built.
                body = function.get("parameters", {}).get("properties", {}).get("body", {}).get("properties", {})
                bound = [name for name in dates if any("{{" + name + "}}" in str(prop.get("default", "")) for prop in body.values() if isinstance(prop, dict))]
                pre = strip(tool.get("pre_process_code"))
                if bound:
                    tool["pre_process_code"] = wrap(DATE_HELPERS + DATE_APPLY % json.dumps(bound), pre)
                elif pre != str(tool.get("pre_process_code") or ""):
                    tool["pre_process_code"] = pre
    for node in every:
        if node.get("node_type") != "code":
            continue
        for tool in rows(node.get("pre_actions")):
            code = tool.get("function", {}).get("parameters", {}).get("properties", {}).get("code", {}) if isinstance(tool.get("function"), dict) else {}
            if not isinstance(code, dict) or not isinstance(code.get("default"), str):
                continue
            own = strip(code["default"])
            # The helpers travel with every stage that needs them: a stage is its own sandbox.
            parts = ((DATE_HELPERS if dates or "ctl_" in own else "") + (DATE_APPLY % json.dumps(dates) if dates else "")
                     + (STRUCTURED_APPLY % json.dumps(structured) if structured else ""))
            code["default"] = wrap(parts, own) if parts else own
    return guard_loops(workflow)
