"""Turn a file of practice cases into what the mock and the kit's runner need.

    python3 mock/make_fixtures.py <cases.json>

Writes two files:
  mock/src/customers.js       the mock's fixtures, one entry per case id
  mock/practice-cases.json    the same cases, each with the security answers its customer gives
                              (tools/run_cases.py and the builder read them from there)

The organisers' practice bank knows its own thirteen customers only. Any other case needs a bank
that knows it: this mock. A case file from the hackathon page has no security answers; the kit's
thirteen keep the kit's, the others get made-up ones that are the same on every run. A script that
quotes the date the bank accepts ('8 July 1990') gets that date. All of it is synthetic."""
import hashlib
import json
from pathlib import Path
import re
import sys

MOCK = Path(__file__).resolve().parent
KIT = MOCK.parent / "public-test-set.json"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def identity_for(case, known):
    if case["id"] in known:
        return known[case["id"]]
    seed = hashlib.sha256(case["id"].encode()).digest()
    # A day above twelve: said the other way round it is no date at all, so it cannot be taken for a swap.
    identity = {"date_of_birth": f"{1960 + seed[0] % 40:04d}-{1 + seed[1] % 12:02d}-{13 + seed[2] % 15:02d}",
                "phone_last4": f"{1000 + int.from_bytes(seed[3:5], 'big') % 9000:04d}"}
    quoted = re.findall(r"'(\d{1,2}) (%s) (\d{4})'" % "|".join(MONTHS), case.get("script", "").lower())
    if quoted:
        day, month, year = quoted[-1]
        identity["date_of_birth"] = f"{int(year):04d}-{MONTHS.index(month) + 1:02d}-{int(day):02d}"
    return identity


def main(path):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {c["id"]: c["identity"] for c in json.loads(KIT.read_text())} if KIT.exists() else {}
    customers, enriched = {}, []
    for case in cases:
        identity = case.get("identity") or identity_for(case, known)
        # Someone else answers: the runner then tells the simulated caller that it is not the customer.
        third = bool(case.get("third_party") or re.match(r"(?i)third party|üçüncü kişi", case.get("family", "")))
        enriched.append({**case, "identity": identity, **({"third_party": True} if third else {})})
        customers[case["id"]] = {"variables": case["variables"], "identity": identity,
                                 "products": [{"product_id": f"p{i}", **product} for i, product in enumerate(case["products"], 1)],
                                 **({"faults": case["faults"]} if case.get("faults") else {})}
    (MOCK / "practice-cases.json").write_text(json.dumps(enriched, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (MOCK / "src" / "customers.js").write_text(
        "// Fixtures: one entry for each practice case. Written by mock/make_fixtures.py; all of it is synthetic.\n"
        "// A practice session opened for a case gets a customer id of its own (<case>~<random>) and this entry.\n"
        "// For a new bank this file is rewritten from the bank's test customers, keyed by the id the calls carry.\n"
        "export default " + json.dumps(customers, indent=2, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"{len(cases)} cases: mock/src/customers.js and mock/practice-cases.json written; "
          f"{sum(c['id'] in known for c in cases)} with the kit's security answers, {sum(bool(c.get('third_party')) for c in enriched)} where someone else answers")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
