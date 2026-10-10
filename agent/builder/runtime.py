"""Controller-owned runtime support compiled into every workflow.

Nothing here comes from a brief. It encodes observed platform behaviour and plain English calendar
language, so that model-written policy code receives usable values:

- response_mapping stores scalars only; a mapped list/object must be materialised for code nodes.
- The platform resolves a `date` extraction against the real clock, not the call's `now` variable,
  so "tomorrow" lands on the wrong day whenever a call is simulated on another date. Spoken dates
  are therefore captured as the customer's words and resolved here against `now`.
"""
import json

START = "# controller: runtime prelude"
END = "# controller: end of runtime prelude"
SAID = ("If the customer states a complete calendar date including its year, give it as YYYY-MM-DD. Otherwise give the customer's own final "
        "words for the day exactly as said (for example: tomorrow, this Friday, the 26th, 6 November) and do not work out a calendar date yourself.")

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
CTL_TENS = dict(twenty=20, thirty=30, forty=40, fifty=50, twentieth=20, thirtieth=30)
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
            for index, name in enumerate(CTL_MONTHS):
                if tok == name or (len(tok) >= 3 and tok != "may" and name.startswith(tok) and tok in (name[:3], name[:4])):
                    month = [index + 1, pos]
        years = [n[0] for n in numbers if 2000 <= n[0] <= 2100]
        days = [n for n in numbers if 1 <= n[0] <= 31]
        near = []
        if month:
            # A month counts only with a day number beside it ("may" is also an ordinary verb).
            near = [n for n in days if n[3] == month[1] or n[2] == month[1] + 1
                    or (n[3] + 1 == month[1] and tokens[n[3]] == "of")
                    or (n[2] == month[1] + 2 and tokens[month[1] + 1] == "the")]
        if near:
            pick = near[0]
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
'''

DATE_APPLY = '''
try:
    for ctl_name in %s:
        ctl_raw = vars.get(ctl_name)
        if not isinstance(ctl_raw, str) or not ctl_raw.strip() or ctl_raw == vars.get(ctl_name + "_iso"):
            continue
        ctl_day = ctl_date(ctl_raw, vars.get("now"))
        vars[ctl_name + "_said"] = ctl_raw
        vars[ctl_name + "_iso"] = ctl_day
        vars[ctl_name] = ctl_day
except Exception:
    pass
'''

STRUCTURED_APPLY = '''
import json
try:
    for ctl_name, ctl_field in %s:
        ctl_cur = vars.get(ctl_name)
        if isinstance(ctl_cur, (list, dict)) and ctl_cur:
            continue
        if isinstance(ctl_cur, str) and ctl_cur.strip()[:1] in ("[", "{"):
            continue
        ctl_saved = vars.get(ctl_name + "_json")
        if isinstance(ctl_saved, str) and ctl_saved.strip()[:1] in ("[", "{"):
            vars[ctl_name] = ctl_saved
            continue
        ctl_rows = {}
        ctl_mark = "_response.data." + ctl_field + "."
        for ctl_key in list(vars.keys()):
            ctl_text = str(ctl_key)
            if ctl_mark not in ctl_text:
                continue
            ctl_rest = ctl_text.split(ctl_mark, 1)[1].split(".")
            if len(ctl_rest) == 2 and ctl_rest[0].isdigit():
                ctl_rows.setdefault(int(ctl_rest[0]), {})[ctl_rest[1]] = vars[ctl_key]
        if ctl_rows:
            vars[ctl_name] = json.dumps([ctl_rows[ctl_i] for ctl_i in sorted(ctl_rows)])
except Exception:
    pass
'''

STRUCTURED_HOOK = '''
import json
try:
    if isinstance(result, dict) and isinstance(result.get("data"), dict):
        for ctl_name, ctl_field in %s:
            if isinstance(result["data"].get(ctl_field), (list, dict)):
                vars[ctl_name] = json.dumps(result["data"][ctl_field])
                vars[ctl_name + "_json"] = vars[ctl_name]
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
    dates = []
    for node in every:
        for item in node.get("extraction_schema") or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            if item.get("type") in ("date", "datetime") or SAID in str(item.get("description", "")):
                item["type"] = "string"
                if SAID not in str(item.get("description", "")):
                    item["description"] = (str(item.get("description", "")).strip() + " " + SAID).strip()
                if item["name"] not in dates:
                    dates.append(item["name"])
    structured = []
    for node in every:
        for placement in ("tools", "pre_actions"):
            for tool in node.get(placement) or []:
                function = tool.get("function") if isinstance(tool, dict) else None
                if not isinstance(function, dict) or function.get("handler") != "__function__:api_call":
                    continue
                contract = contracts["operations"].get(function.get("name"))
                if not contract:
                    continue
                schema = contract["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("properties", {})
                mappings = tool.get("response_mapping") if placement == "tools" else node.get("response_mapping")
                pairs = []
                for mapping in mappings or []:
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
    parts = (DATE_HELPERS + DATE_APPLY % json.dumps(dates) if dates else "") + (STRUCTURED_APPLY % json.dumps(structured) if structured else "")
    for node in every:
        if node.get("node_type") != "code":
            continue
        for tool in node.get("pre_actions") or []:
            code = tool.get("function", {}).get("parameters", {}).get("properties", {}).get("code", {}) if isinstance(tool, dict) and isinstance(tool.get("function"), dict) else {}
            if isinstance(code.get("default"), str):
                code["default"] = wrap(parts, code["default"]) if parts else strip(code["default"])
    return guard_loops(workflow)
