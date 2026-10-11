"""How callers talk: a number in two parts, corrections, other things, a question back, amounts and
dates in words. Turkish and English. The phrases are general language, not taken from any case."""
import pytest
from conftest import route
from builder import runtime
from builder.contracts import compile_workflow
from builder.validation import code_errors

NOW = '2026-10-14T11:00'   # a Wednesday


def helpers():
    scope = {}
    exec(runtime.DATE_HELPERS, scope, scope)
    return scope


H = helpers()


# ------------------------------------------------------------------ H5: dates in words

@pytest.mark.parametrize('said,expected', [
    ('yarın', '2026-10-15'), ('yarin', '2026-10-15'), ('bugün', '2026-10-14'), ('hemen bugün öderim', '2026-10-14'),
    ('öbür gün', '2026-10-16'), ('yarından sonra', '2026-10-16'), ('yarın değil öbür gün', '2026-10-16'),
    ('bu cuma', '2026-10-16'), ('cuma günü', '2026-10-16'), ('cumaya kadar', '2026-10-16'), ('gelecek cuma', '2026-10-23'),
    ('haftaya salı', '2026-10-20'), ('gelecek hafta salı', '2026-10-20'), ('önümüzdeki pazartesi', '2026-10-19'),
    ('bu hafta perşembe', '2026-10-15'), ('cumartesi', '2026-10-17'), ('pazar günü', '2026-10-18'),
    ('ayın yirmi altısı', '2026-10-26'), ("ayın 26'sı", '2026-10-26'), ("26'sında", '2026-10-26'), ('yirmi altısında', '2026-10-26'),
    ('ayın beşi', '2026-11-05'), ('ayın on beşinde', '2026-10-15'), ('ayın biri', '2026-11-01'),
    ('6 Kasım', '2026-11-06'), ('altı Kasım', '2026-11-06'), ('Kasımın altısı', '2026-11-06'), ("6 Kasım'da", '2026-11-06'),
    ('26 Ekim 2026', '2026-10-26'), ('yirmi altı Ekim iki bin yirmi altı', '2026-10-26'), ('5 Ocak', '2027-01-05'),
    ('3 gün sonra', '2026-10-17'), ('üç gün sonra', '2026-10-17'), ('iki hafta sonra', '2026-10-28'),
    ('bir hafta sonra', '2026-10-21'), ('on gün sonra', '2026-10-24'),
    ('26.10.2026', '2026-10-26'), ('26.10', '2026-10-26'), ('26/10', '2026-10-26'), ('05.01', '2027-01-05'),
    # A transcript without Turkish letters reads the same.
    ('ayin yirmi altisi', '2026-10-26'), ('kasimin altisi', '2026-11-06'), ('obur gun', '2026-10-16'), ('haftaya sali', '2026-10-20'),
    # Everyday words that only look like numbers are no day.
    ('onu yarın öderim', '2026-10-15'), ('ona göre cuma olsun', '2026-10-16'), ('biri değil, yarın', '2026-10-15'),
    # A time of day is not a day of the month: "on birde" is at eleven, "on birinde" is on the eleventh.
    ('yarın sabah on birde', '2026-10-15'), ('bugün saat üçte', '2026-10-14'), ("yarın 11'de", '2026-10-15'),
    ("yarın 10.30'da", '2026-10-15'), ('cuma saat ikide', '2026-10-16'), ("saat 5'e kadar yarın", '2026-10-15'),
    ('on birinde', '2026-11-11'), ("ayın 11'inde", '2026-11-11'), ('ayın onunda', '2026-11-10'),
    # The month after this one, and a month named with "ayı".
    ('gelecek ayın yirmisi', '2026-11-20'), ("önümüzdeki ayın 5'i", '2026-11-05'), ('Mart ayının on dördünde', '2027-03-14'),
    ('pazartesi değil salı', '2026-10-20'), ("26.10'da", '2026-10-26'),
    # A period is not a day: the agent asks for the day.
    ('ay sonu', ''), ('ayın sonunda', ''), ('gelecek hafta', ''), ('haftaya', ''), ('maaş gününde', ''),
    ('maaşım yatınca', ''), ('birkaç gün sonra', ''), ('on gün içinde', ''), ('ay başında', ''), ('', ''),
])
def test_turkish_days_resolve_against_call_now(said, expected):
    assert H['ctl_date'](said, NOW) == expected


@pytest.mark.parametrize('said,expected', [
    ('Tuesday next week', '2026-10-20'), ('next week Tuesday', '2026-10-20'), ('10/26', '2026-10-26'),
    ('I will pay on the 26th', '2026-10-26'), ('I’ll pay tomorrow', '2026-10-15'), ('on Friday', '2026-10-16'),
    ('the 5th of next month', '2026-11-05'), ('No, I can pay on Friday', '2026-10-16'), ('I have no money until the 30th', '2026-10-30'),
    # An amount or a time written with a dot is no date.
    ('5.10 dollars', ''), ('12.50', ''), ('tomorrow at 10.30', '2026-10-15'),
])
def test_english_days_still_resolve(said, expected):
    assert H['ctl_date'](said, NOW) == expected
    # "Tuesday next week" names its week, whatever reading "next Tuesday" is given.
    assert H['ctl_date']('Tuesday next week', NOW, 'next_occurrence') == '2026-10-20'
    assert H['ctl_date']('haftaya salı', NOW, 'next_occurrence') == '2026-10-20'
    assert H['ctl_date']('gelecek cuma', NOW, 'next_occurrence') == '2026-10-16'


# ------------------------------------------------------------------ H2: corrections

@pytest.mark.parametrize('said,expected', [
    ('ayın yirmi biri, pardon, yirmisi', '2026-10-20'), ('cuma, yok yok perşembe', '2026-10-15'),
    ('yarın, yani ayın on beşi', '2026-10-15'), ('ayın yirmisi, düzeltiyorum, yirmi ikisi', '2026-10-22'),
    ('the 21st, sorry, I mean the 20th', '2026-10-20'), ('Friday, no wait, Thursday', '2026-10-15'),
    ('the 30th, actually the 29th', '2026-10-29'),
    # A correction word with nothing after it corrects nothing.
    ('Friday, sorry about the noise', '2026-10-16'), ('yarın, pardon', '2026-10-15'),
])
def test_the_corrected_day_wins(said, expected):
    assert H['ctl_date'](said, NOW) == expected


# ------------------------------------------------------------------ H1: a date of birth, whole or in parts

@pytest.mark.parametrize('said,expected', [
    ('14 Mart 1988', '1988-03-14'), ('on dört Mart bin dokuz yüz seksen sekiz', '1988-03-14'),
    ('14.03.1988', '1988-03-14'), ('14/03/1988', '1988-03-14'), ('doğum tarihim 5 Aralık 1975', '1975-12-05'),
    ('1988 yılının 14 Martı', '1988-03-14'), ('on dort mart bin dokuz yuz seksen sekiz', '1988-03-14'),
    # No year, no day or a year of two digits: never filled in. The agent asks for what is missing.
    ('on dört Mart', ''), ('bin dokuz yüz seksen sekiz', ''), ('on dört Mart seksen sekiz', ''), ('Mart 1988', ''),
    # A second answer after a first: the latest complete date.
    ('12 Temmuz 1991, pardon, 21 Ağustos 1992', '1992-08-21'), ('14.03.1988 değil 15.03.1988', '1988-03-15'),
    # A date said only as numbers is day, then month, then year.
    ('14 3 1988', '1988-03-14'), ('on dört üç bin dokuz yüz seksen sekiz', '1988-03-14'), ('fourteen three nineteen eighty eight', '1988-03-14'),
    ('on dört, üç, bin dokuz yüz seksen sekiz', '1988-03-14'), ('14 13 1988', ''), ('dört dört yedi bir', ''),
    # The month that was said is the month of the answer, wherever the day stands: never a wrong date sent as an answer.
    ('Mart ayının on dördü, bin dokuz yüz seksen sekiz', '1988-03-14'), ('in March on the 14th 1988', ''),
])
def test_identity_dates_in_turkish_never_get_a_year_they_were_not_given(said, expected):
    assert H['ctl_identity_date'](said) == expected


def test_a_date_of_birth_in_two_parts_is_complete_only_when_joined():
    first, rest = 'on dört Mart', 'bin dokuz yüz seksen sekiz'
    assert H['ctl_identity_date'](first) == '' and H['ctl_identity_date'](rest) == ''
    assert H['ctl_identity_date'](first + ' ' + rest) == '1988-03-14'
    assert H['ctl_identity_date']('the fourteenth of March' + ' ' + 'nineteen eighty eight') == '1988-03-14'


# ------------------------------------------------------------------ H1: digits, however they are said

@pytest.mark.parametrize('said,expected', [
    ('dört dört yedi bir', '4471'), ('kırk dört yetmiş bir', '4471'), ('forty-four seventy-one', '4471'),
    ('sıfır beş otuz iki', '0532'), ('çift sıfır yedi bir', '0071'), ('463', '463'), ('dört yüz altmış üç', '463'),
    ('four sixty three', '463'), ('four hundred and sixty three', '463'), ('elli bir', '51'), ('fifty one', '51'),
    ('44 71', '4471'), ('on bir yirmi iki', '1122'), ('yüz bir', '101'), ('bin dokuz yüz seksen sekiz', '1988'),
    ('nineteen eighty eight', '1988'), ('dort dort yedi bir', '4471'), ('zero three five eight', '0358'),
    # The corrected number wins.
    ('4471, pardon, 4472', '4472'), ('dört dört yedi bir, yok, dört dört yedi iki', '4472'),
    ('four four seven one, sorry, four four seven two', '4472'), ('4471 sorry about the noise', '4471'),
    # A question back, a hold or a story is no answer: nothing is sent, and no attempt is lost.
    ('bunu neden soruyorsunuz?', ''), ('why do you need that?', ''), ('bir saniye', ''), ('bir dakika bakayım', ''),
    ('one moment', ''), ('it is four four seven one', ''), ('', ''),
])
def test_digits_in_any_wording(said, expected):
    assert H['ctl_digits'](said) == expected


def test_digits_with_the_wanted_length_take_the_last_ones():
    assert H['ctl_digits']('0532 123 44 71', 4) == '4471' and H['ctl_digits']('kırk dört', 4) == '44'
    assert H['ctl_digits']('on', 2) == '10' and H['ctl_digits']('I will pay on Friday') == ''


def collect(replies, count):
    values, seen = {}, []
    for said in replies:
        seen.append((H['ctl_collect'](values, 'no', said, count), values['no_parts'], values['no_complete'], values['no_heard']))
    return seen, values


def test_a_number_in_two_parts_is_kept_and_joined():
    # "463..." then "51": the example we were given.
    seen, values = collect(['463', '51'], 5)
    assert seen == [('', '463', 'no', 'yes'), ('46351', '', 'yes', 'yes')] and values['no'] == '46351'
    seen, _ = collect(['dört yüz altmış üç', 'elli bir'], 5)
    assert seen[-1][0] == '46351'
    seen, _ = collect(['kırk dört', 'yetmiş bir'], 4)
    assert [s[0] for s in seen] == ['', '4471']
    seen, _ = collect(['four four', 'seven one'], 4)
    assert [s[0] for s in seen] == ['', '4471']
    # Three parts, zeros kept.
    seen, _ = collect(['sıfır beş', '3', 'iki'], 4)
    assert [s[:2] for s in seen] == [('', '05'), ('', '053'), ('0532', '')]


def test_a_question_between_the_parts_loses_nothing():
    seen, _ = collect(['463', 'bunu neden soruyorsunuz?', 'bir saniye', '51'], 5)
    assert seen == [('', '463', 'no', 'yes'), ('', '463', 'no', 'no'), ('', '463', 'no', 'no'), ('46351', '', 'yes', 'yes')]


def test_a_correction_replaces_what_was_kept():
    seen, _ = collect(['463', 'pardon, 464', '51'], 5)
    assert [s[:2] for s in seen] == [('', '463'), ('', '464'), ('46451', '')]
    seen, _ = collect(['46', 'sorry, 47', '351'], 5)
    assert [s[:2] for s in seen] == [('', '46'), ('', '47'), ('47351', '')]
    # The whole number said again, or said at once, is the answer; so is a second answer after a first.
    seen, values = collect(['44', '4471'], 4)
    assert seen[-1][0] == '4471'
    seen, values = collect(['4401', '4410'], 4)
    assert [s[0] for s in seen] == ['4401', '4410'] and values['no'] == '4410'
    # More digits than were asked for: the last ones.
    assert collect(['0532 123 44 71'], 4)[0][0][0] == '4471'
    # A filler that is also a correction word still completes the number.
    assert collect(['463', 'yani 51'], 5)[0][-1][0] == '46351'
    # Without a known length nothing can be called incomplete: the reply is the number.
    assert collect(['463'], 0)[0][0] == ('463', '', 'yes', 'yes')


def test_collect_never_raises_on_damaged_state():
    values = {'no_parts': None, 'no_complete': 5}
    assert H['ctl_collect'](values, 'no', None, 'four') == '' and values['no_complete'] == 'no'
    assert H['ctl_collect'](values, 'no', '12', '2') == '12'


# ------------------------------------------------------------------ H5: amounts in words

@pytest.mark.parametrize('said,expected', [
    ('420', '420.00'), ('637.50', '637.50'), ('637,50', '637.50'), ('1.250,50 TL', '1250.50'), ('1,250.50', '1250.50'),
    ('1.250', '1250.00'), ('1250 TL', '1250.00'), ("1.250 TL'yi", '1250.00'), ("500'ü", '500.00'),
    ('bin iki yüz elli lira', '1250.00'), ('bin iki yüz elli lira elli kuruş', '1250.50'), ('beş yüz kırk lira elli kuruş', '540.50'),
    ('540 lira 50', '540.50'), ('yüz elli buçuk lira', '150.50'), ('iki bin beş yüz', '2500.00'), ('2 bin 500 lira', '2500.00'),
    ('250 bin lira', '250000.00'), ('on lira', '10.00'), ('on bin lira', '10000.00'), ('bin', '1000.00'), ('yüz', '100.00'),
    ('bin iki yuz elli lira', '1250.00'), ('elli kuruş', '0.50'),
    ('four hundred and fifty-five', '455.00'), ('six hundred thirty seven dollars and fifty cents', '637.50'),
    ('twelve hundred', '1200.00'), ('one thousand two hundred fifty', '1250.00'), ('a hundred dollars', '100.00'),
    # The number that carries the currency is the amount; a day said with it is not.
    ('540 on Friday', '540.00'), ('five hundred on the 27th', '500.00'), ('bin lirayı ayın yirmi altısında öderim', '1000.00'),
    ('yirmi altısında bin öderim', '1000.00'), ('beş yüz kırk lirayı kabul ediyorum, yirmi yedisinde', '540.00'),
    ("26'sında 300", '300.00'), ("300 lira 26'sında", '300.00'), ('500 değil 400', '400.00'), ('on yedi lira kırk kuruş', '17.40'),
    # The corrected amount wins.
    ('beş yüz, pardon, dört yüz lira', '400.00'), ('five hundred, sorry, four hundred', '400.00'), ('500, no problem', '500.00'),
    # A number the extraction model has already written.
    (1250.5, '1250.50'), (420, '420.00'), ('420.0', '420.00'),
])
def test_amounts_in_words_and_digits(said, expected):
    assert H['ctl_amount'](said) == expected


@pytest.mark.parametrize('said', [
    'tamamını', 'the full amount', 'asgari tutarı ödeyeyim', 'yarısını', 'the minimum',   # a reference has no number
    'twelve fifty', 'two fifty', '500 ya da 600', 'five or six hundred',                  # two readings
    'bir sorum var', 'one moment', 'bir dakika', 'onu ödeyemem', 'bunu neden soruyorsunuz?',   # everyday words
    'beşte öderim', 'yirmi altısında', "26'sında",                                             # a time of day, a day
    'geçen hafta on yedi lira kırk kuruş ödedim, şimdi beş yüz lira',                     # two amounts: ask
    '26.10.2026', '', None, 0, True,
])
def test_what_is_no_single_amount_is_empty(said):
    assert H['ctl_amount'](said) == ''


# ------------------------------------------------------------------ where the helpers are compiled in

def code_of(compiled, key):
    return compiled['nodes'][key]['pre_actions'][0]['function']['parameters']['properties']['code']['default']


def code_stage(name, source, *routes):
    return {'name': name, 'node_type': 'code', 'code': source, 'transitions': [route(target, condition) for target, condition in routes]}


def test_every_helper_runs_from_the_part_compiled_for_it():
    calls = {'ctl_date': "ctl_date('yarın', '2026-10-14T11:00')", 'ctl_identity_date': "ctl_identity_date('14 Mart 1988')",
             'ctl_digits': "ctl_digits('kırk dört yetmiş bir')", 'ctl_amount': "ctl_amount('bin iki yüz elli lira')",
             'ctl_collect': "ctl_collect({}, 'n', '4471', 4)", 'ctl_add_business_days': "ctl_add_business_days('2026-10-14', 1, [0,1,2,3,4], [])",
             'ctl_proposal': "ctl_proposal({}, 'p1', '10', '2026-10-15')", 'ctl_slot': "str(ctl_slot({}, 'n', 'x', 'x', True, 1))"}
    expected = {'ctl_date': '2026-10-15', 'ctl_identity_date': '1988-03-14', 'ctl_digits': '4471', 'ctl_amount': '1250.00',
                'ctl_collect': '4471', 'ctl_add_business_days': '2026-10-15', 'ctl_proposal': '1', 'ctl_slot': 'True'}
    whole = len(runtime.DATE_HELPERS)
    for name, call in calls.items():
        part = runtime.helpers_for({name})
        scope = {}
        exec(part + '\nresult = ' + call, scope, scope)
        assert scope['result'] == expected[name], name
        assert len(part) < whole and code_errors('try:\n    pass\nexcept Exception:\n    pass\n' + part) == [], name
    assert runtime.helpers_for({'ctl_not_a_helper'}) == '' and runtime.helpers_for(set()) == ''
    # The business-day helpers do not drag the speech helpers along.
    assert 'ctl_tr' not in runtime.helpers_for({'ctl_add_business_days'}) and len(runtime.helpers_for({'ctl_add_business_days'})) < 2500


def test_words_are_converted_in_the_first_code_stage_after_they_were_said(spec, contracts):
    w = spec['workflow']
    w['nodes']['verify']['extraction_schema'] = [
        {'name': 'pay_day', 'type': 'date', 'description': 'Day offered.', 'min_confidence': 0.7},
        {'name': 'pay_amount', 'type': 'amount', 'description': 'Amount offered.', 'min_confidence': 0.7}]
    w['nodes']['verify']['transitions'] = [route('first'), route('verify')]
    w['nodes']['first'] = code_stage('first', "try:\n    vars['day_seen'] = str(vars.get('pay_day'))\n    vars['sum_seen'] = str(vars.get('pay_amount'))\nexcept Exception:\n    vars['day_seen'] = ''\n", ('second', None))
    w['nodes']['second'] = code_stage('second', "try:\n    vars['n'] = ctl_add_business_days(vars.get('pay_day'), 1, [0, 1, 2, 3, 4], [])\nexcept Exception:\n    vars['n'] = ''\n", ('third', None))
    w['nodes']['third'] = code_stage('third', "try:\n    vars['t'] = 'x'\nexcept Exception:\n    vars['t'] = ''\n", ('check', None))
    once = compile_workflow(w, contracts)[0]
    assert compile_workflow(once, contracts)[0] == once
    day, amount = once['nodes']['verify']['extraction_schema']
    assert day['type'] == amount['type'] == 'string' and runtime.SAID in day['description']
    assert runtime.SAID_AMOUNT in amount['description'] and runtime.ONE_AMOUNT in amount['description']
    first, second, third = (code_of(once, key) for key in ('first', 'second', 'third'))
    # The first code stage converts; the second carries only the helper it calls; the third carries nothing.
    assert 'def ctl_date' in first and 'def ctl_amount' in first
    assert 'def ctl_add_business_days' in second and 'def ctl_date' not in second and 'def ctl_amount' not in second
    assert runtime.START not in third
    for code in (first, second):
        assert code_errors(code) == [] and code.count(runtime.START) == 1
    scope = {'vars': {'now': NOW, 'pay_day': 'haftaya salı', 'pay_amount': 'bin iki yüz elli lira elli kuruş'}}
    exec(first, scope, scope)
    out = scope['vars']
    assert (out['day_seen'], out['sum_seen']) == ('2026-10-20', '1250.50')
    assert (out['pay_day_said'], out['pay_amount_said']) == ('haftaya salı', 'bin iki yüz elli lira elli kuruş')
    exec(second, scope, scope)
    assert scope['vars']['n'] == '2026-10-21'
    exec(first, scope, scope)   # entered again: what is converted stays as it is
    assert (scope['vars']['pay_day'], scope['vars']['pay_amount']) == ('2026-10-20', '1250.50')
    # A reference has no number, a period is no day: both arrive as '' and keep the words.
    scope = {'vars': {'now': NOW, 'pay_day': 'ay sonu', 'pay_amount': 'tamamını'}}
    exec(first, scope, scope)
    assert (scope['vars']['pay_day'], scope['vars']['pay_amount'], scope['vars']['pay_amount_said']) == ('', '', 'tamamını')
    # A number the extraction model wrote itself is left alone.
    scope = {'vars': {'now': NOW, 'pay_amount': 1250.5}}
    exec(first, scope, scope)
    assert scope['vars']['pay_amount'] == 1250.5


def test_an_amount_bound_to_a_tool_is_converted_in_its_hook(spec, contracts):
    w = spec['workflow']
    w['nodes']['verify']['extraction_schema'].append({'name': 'pay_amount', 'type': 'amount', 'description': 'Amount offered.', 'min_confidence': 0.7})
    w['nodes']['account']['transitions'] = [route('promise')]
    w['nodes']['promise'] = {'name': 'promise', 'node_type': 'api_request', 'transitions': [route('close')],
                             'pre_actions': [{'bank_operation': 'create_promise', 'description': 'CALL when confirmed.',
                                              'bindings': {'product_id': '{{product_id}}', 'amount': '{{pay_amount}}', 'date': '{{dob}}'}}]}
    hook = compile_workflow(w, contracts)[0]['nodes']['promise']['pre_actions'][0]['pre_process_code']
    assert code_errors(hook, True) == [] and 'def ctl_amount' in hook and 'def ctl_date' in hook
    scope = {'vars': {'now': NOW, 'pay_amount': '1.250,50 TL', 'dob': 'yarın'}, 'config': {}}
    exec(hook, scope, scope)
    assert scope['vars']['pay_amount'] == '1250.50' and scope['vars']['dob'] == '2026-10-15'


def test_the_compiled_practice_design_is_smaller_and_its_code_still_runs(contracts):
    import json
    from pathlib import Path
    from builder.config import AGENT
    from builder.validation import validate
    runs = sorted(AGENT.glob('artifacts/2026*/pinned_root.json'))
    if not runs:
        pytest.skip('no saved design on this machine')
    for path in runs[-3:]:
        saved = json.loads(Path(path).read_text())
        compiled = compile_workflow(saved['spec']['workflow'], contracts)[0]
        size = len(json.dumps(compiled, separators=(',', ':')))
        every = sum(len(runtime.DATE_HELPERS) for node in compiled['nodes'].values() if node.get('node_type') == 'code')
        assert size < every, (path, size, every)   # less than the helper block alone took when every code stage carried it
        for key, node in compiled['nodes'].items():
            if node.get('node_type') == 'code':
                compile(code_of(compiled, key), key, 'exec')
        assert not [e for e in validate(compiled, contracts)['errors'] if 'is not defined' in e]
