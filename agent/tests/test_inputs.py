"""The form of the final: `build.py <case_folder> <mock_url>`. A folder of mixed file types, a tool
contract that may be YAML or only described in the documents, and tools that call the team's own mock."""
from copy import deepcopy
import json
from pathlib import Path
import zipfile

import pytest
from builder.build import Builder, case, echo, main
from builder.config import KIT, Config
from builder.contracts import CALL_HEADER, compile_openapi, compile_workflow
from builder.sources import case_files, is_api, read_document
from builder.validation import validate
from test_pipeline import FakeFreya, roles

MOCK = 'https://bank-mock.example.workers.dev'
WORD = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def docx(path, paragraphs, table):
    para = lambda text, style='': f'<w:p>{"<w:pPr><w:pStyle w:val=%r/></w:pPr>" % style if style else ""}<w:r><w:t>{text}</w:t></w:r></w:p>'
    rows = ''.join('<w:tr>' + ''.join(f'<w:tc>{para(cell)}</w:tc>' for cell in row) + '</w:tr>' for row in table)
    body = ''.join(para(text, style) for text, style in paragraphs) + f'<w:tbl>{rows}</w:tbl>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', f'<?xml version="1.0"?><w:document xmlns:w="{WORD}"><w:body>{body}</w:body></w:document>')


def xlsx(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{SHEET}" xmlns:r="{REL}"><sheets><sheet name="Müşteriler" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{SHEET}"><si><t>Ad</t></si><si><t>Doğum tarihi</t></si><si><t>Borç</t></si><si><t>Ayşe Yılmaz</t></si></sst>')
        archive.writestr('xl/styles.xml', f'<styleSheet xmlns="{SHEET}"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        archive.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{SHEET}"><sheetData>'
                         '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
                         '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2" s="1"><v>32216</v></c><c r="C2"><v>1250.5</v></c></row>'
                         '</sheetData></worksheet>')


@pytest.fixture
def folder(work):
    """A case folder like the one the organisers describe: nothing in it is from a real case."""
    root = work / 'Ornek-Vaka'
    (root / 'ekler').mkdir(parents=True)
    (root / 'zz-notlar.txt').write_text('Görüşmeler kayıt altındadır.\n', encoding='utf-8')
    (root / 'README.md').write_text('# Dosyalar\nBRIEF.md: özet. sozlesme.yaml: servis sözleşmesi.\n', encoding='utf-8')
    (root / 'BRIEF.md').write_text('# Özet\n1. Önce kimlik doğrulanır.\n2. Borç bilgisi sonra söylenir.\n', encoding='utf-8')
    docx(root / 'analiz.docx', [('Analiz', 'Heading1'), ('Müşteri önce doğrulanır.', '')], [['Kod', 'Anlam'], ['odeme_sozu', 'Ödeme sözü alındı']])
    xlsx(root / 'test-musterileri.xlsx')
    (root / 'duyuru.pdf').write_bytes(b'%PDF-1.4\n1 0 obj\n<<>>\nstream\nBT (Odeme tarihi is gunu olmalidir) Tj ET\nendstream\nendobj\n%%EOF')
    (root / 'ekler' / 'akis.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
    (root / 'ekler' / 'eski.doc').write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00')
    (root / '.DS_Store').write_bytes(b'\x00\x01')
    import yaml
    (root / 'sozlesme.yaml').write_text(yaml.safe_dump(json.loads((KIT / 'tools/openapi.json').read_text()), allow_unicode=True), encoding='utf-8')
    return root


def test_a_case_folder_is_read_whole_and_what_cannot_be_read_is_noted(folder):
    files = [p.name for p in case_files(folder)]
    assert files[:2] == ['BRIEF.md', 'README.md'] and '.DS_Store' not in files
    word, _ = read_document(folder / 'analiz.docx')
    assert word.splitlines()[0] == '# Analiz' and 'Müşteri önce doğrulanır.' in word and '| odeme_sozu | Ödeme sözü alındı |' in word
    sheet, _ = read_document(folder / 'test-musterileri.xlsx')
    assert '## Müşteriler' in sheet and 'Ad | Doğum tarihi | Borç' in sheet and 'Ayşe Yılmaz | 1988-03-14 | 1250.5' in sheet
    assert read_document(folder / 'ekler' / 'akis.png') == (None, 'a .png file is not a document this builder reads')
    assert is_api(folder / 'sozlesme.yaml') and not is_api(folder / 'BRIEF.md')
    given = case([str(folder), MOCK])
    names = [Path(p).name for p in given['briefs']]
    assert names[:2] == ['BRIEF.md', 'README.md'] and {'analiz.docx', 'test-musterileri.xlsx', 'zz-notlar.txt'} <= set(names)
    assert Path(given['openapi']).name == 'sozlesme.yaml' and given['mock_url'] == MOCK and given['name'] == 'Ornek-Vaka'
    noted = ' '.join(given['notes'])
    assert 'akis.png' in noted and 'eski.doc' in noted
    # A PDF is read where it can be and noted where it cannot; either way it never stops the build.
    assert ('duyuru.pdf' in names) != ('duyuru.pdf' in noted)


def test_a_turkish_windows_file_and_a_broken_one_do_not_stop_the_reading(work):
    (work / 'duyuru.txt').write_bytes('Ödeme sözü için gün seçilir.'.encode('cp1254'))
    assert read_document(work / 'duyuru.txt')[0] == 'Ödeme sözü için gün seçilir.'
    (work / 'bozuk.docx').write_bytes(b'not a zip')
    (work / 'bos.md').write_text('   \n')
    assert read_document(work / 'bozuk.docx')[0] is None and 'could not be read' in read_document(work / 'bozuk.docx')[1]
    assert read_document(work / 'bos.md') == (None, 'empty')
    (work / 'sayfa.html').write_text('<html><style>p{}</style><body><h1>Duyuru</h1><p>Ödeme &amp; tarih</p></body></html>', encoding='utf-8')
    assert read_document(work / 'sayfa.html')[0].splitlines() == ['Duyuru', 'Ödeme & tarih']


def test_the_command_line_takes_files_a_folder_and_one_mock_address(folder, work):
    with pytest.raises(ValueError, match='More than one mock'): case([str(folder), MOCK, MOCK + '/x'])
    with pytest.raises(ValueError, match='No such file'): case([str(work / 'missing.md')])
    brief_a = str(KIT / 'briefs/brief-a.md')
    # The practice form is unchanged.
    assert case([brief_a]) == {'briefs': [brief_a], 'openapi': str(KIT / 'tools/openapi.json'), 'mock_url': None, 'name': None, 'notes': []}
    assert case([brief_a], mock_url=MOCK)['mock_url'] == MOCK
    # Without a tool API file a brief from outside the kit needs the mock address: then the contract is written from the documents.
    (folder / 'sozlesme.yaml').unlink()
    assert case([str(folder), MOCK])['openapi'] is None
    with pytest.raises(ValueError, match='needs its own tool API'): case([str(folder)])


def test_with_a_mock_address_every_tool_calls_the_mock(spec, folder):
    plain = compile_openapi(KIT / 'tools/openapi.json')
    mocked = compile_openapi(folder / 'sozlesme.yaml', server=MOCK)
    assert set(mocked['operations']) == set(plain['operations']) and mocked['sha256'] != plain['sha256']
    # A bare mock host keeps the path of the contract's own server; a mock address with a path is taken as it is.
    assert mocked['operations']['get_account']['url'] == MOCK + '/v1/get_account'
    assert compile_openapi(KIT / 'tools/openapi.json', server=MOCK + '/api/')['operations']['get_account']['url'] == MOCK + '/api/get_account'
    for bad in ('http://plain.example', 'https://user:pw@mock.example', 'mock.example', 'https://mock.example/?x=1'):
        with pytest.raises(ValueError, match='mock address'): compile_openapi(KIT / 'tools/openapi.json', server=bad)
    compiled = compile_workflow(spec['workflow'], mocked)[0]
    assert validate(compiled, mocked)['valid'], validate(compiled, mocked)['errors']
    tools = [tool for node in compiled['nodes'].values() for tool in node.get('pre_actions', []) if tool['function']['handler'] == '__function__:api_call']
    assert tools and all(tool['function']['parameters']['properties']['url']['default'].startswith(MOCK + '/v1/') for tool in tools)
    assert all(tool['function']['parameters']['properties']['headers']['properties'][CALL_HEADER[0]]['default'] == CALL_HEADER[1] for tool in tools)
    # The bank's own contract sends no such header, and a workflow built for the mock does not pass as one for the bank.
    assert CALL_HEADER[0] not in json.dumps(compile_workflow(spec['workflow'], plain)[0])
    assert not validate(compiled, plain)['valid']
    # A contract with security or without a server is the bank's business; the mock needs neither.
    secured = json.loads((KIT / 'tools/openapi.json').read_text())
    secured.update(security=[{'key': []}], servers=[])
    (folder / 'secured.json').write_text(json.dumps(secured))
    assert compile_openapi(folder / 'secured.json', server=MOCK)['operations']['close_call']['url'] == MOCK + '/close_call'
    with pytest.raises(ValueError): compile_openapi(folder / 'secured.json')


def build(work, spec, requirements, given, seen, contract_answers=(), scenarios=None, **more):
    answers = list(contract_answers)
    base = roles(spec, requirements, [], seen)
    class Roles(base):
        def ask(self, role, purpose, instruction, payload, schema, max_tokens=None):
            if role == 'ContractAgent':
                self.calls += 1
                seen.append((role, deepcopy(payload)))
                return deepcopy(answers.pop(0))
            if role == 'ScenarioAgent':
                return {'scenarios': scenarios or []}     # these documents describe no example call unless a test gives some
            return super().ask(role, purpose, instruction, payload, schema, max_tokens)
    builder = Builder(Config(artifacts=work, tracing=False), given['briefs'], given['openapi'], roles_factory=Roles, adapter_factory=FakeFreya,
                      mock_url=given['mock_url'], name=given['name'], notes=given['notes'], observer=echo, **more)
    builder.submission_dir = work / 'out'
    return builder, builder.run()


def test_a_folder_build_exports_an_agent_whose_tools_call_the_mock(work, spec, requirements, folder, capsys):
    seen = []
    builder, result = build(work, spec, requirements, case([str(folder), MOCK]), seen)
    assert result['status'] == 'exported' and result['simulations'] == 0 and result['mock_url'] == MOCK
    assert builder.slot == 'builder-Ornek-Vaka' and Path(result['submission_path']).name == 'Ornek-Vaka.workflow.json'
    exported = json.loads(Path(result['submission_path']).read_text())['workflow']
    urls = [tool['function']['parameters']['properties']['url']['default'] for node in exported['nodes'].values() for tool in node.get('pre_actions', []) if tool['function']['handler'] == '__function__:api_call']
    assert urls and all(url.startswith(MOCK) for url in urls) and 'freya-bank-mock' not in json.dumps(exported)
    # The designer was given every document that could be read, the brief first.
    designer = next(payload for role, payload in seen if role == 'ADASDesignerAgent')
    assert [Path(d['path']).name for d in designer['documents']][:2] == ['BRIEF.md', 'README.md'] and len(designer['documents']) >= 5
    # The trace goes to stderr line by line, so `2>&1 | tee` holds all of it: the sources, the model calls, the end.
    err = capsys.readouterr().err
    assert 'run_start' in err and 'sources_read' in err and 'akis.png' in err and 'measurement_skipped' in err and 'run_end' in err
    assert Path(result['trace_path']).read_text().count('\n') == err.count('\n')


def test_without_a_tool_api_file_the_contract_is_written_from_the_documents(work, spec, requirements, folder):
    (folder / 'sozlesme.yaml').unlink()
    api = json.loads((KIT / 'tools/openapi.json').read_text())
    seen = []
    # The first answer has no operations; the builder says what was wrong and takes the second.
    builder, result = build(work, spec, requirements, case([str(folder), MOCK]), seen, [{'openapi': {'openapi': '3.0.3', 'paths': {}}}, {'openapi': api, 'notes': ['Zaman aşımı belirtilmemiş']}])
    asked = [payload for role, payload in seen if role == 'ContractAgent']
    assert len(asked) == 2 and asked[0]['server'] == MOCK and asked[0]['compiler_errors'] == [] and 'no supported operations' in asked[1]['compiler_errors'][0]
    assert result['status'] == 'exported' and builder.openapi_path.name == 'derived.openapi.2.json'
    assert builder.contracts['operations']['verify_identity']['url'] == MOCK + '/v1/verify_identity'
    trace = (builder.root / 'build_trace.log').read_text()
    assert 'contract_rejected' in trace and 'contract_written' in trace and 'written from the documents' in trace
    # Two answers that cannot be used leave no contract, and so no agent: said plainly, with the reason.
    with pytest.raises(ValueError, match='No usable tool contract'):
        build(work, spec, requirements, case([str(folder), MOCK]), [], [{'openapi': {}}, {'openapi': {'openapi': '3.0.3', 'paths': {}}}])


def test_practice_cases_of_your_own_run_on_your_own_bank(work, spec, requirements):
    from builder.freya_adapter import practice_suite
    from builder.contracts import source_documents
    brief = [str(KIT / 'briefs/brief-a.md')]
    kit = json.loads((KIT / 'public-test-set.json').read_text())
    own = [{**kit[0], 'id': 'OWN-01'}, {**kit[1], 'id': 'OWN-02', 'third_party': True}, {**kit[10], 'id': 'OWN-03'}]
    path = work / 'cases.json'
    path.write_text(json.dumps(own))
    suite, cases = practice_suite(path, source_documents(brief))
    assert suite.case_ids == ('OWN-01', 'OWN-02') and suite.evidence_type == 'generated'       # the Brief B case is left out of a Brief A build
    assert practice_suite(path, source_documents(brief + [str(KIT / 'briefs/brief-b.md')]))[0].case_ids == ('OWN-03',)
    without = work / 'bare.json'
    without.write_text(json.dumps([{k: v for k, v in own[0].items() if k != 'identity'}]))
    with pytest.raises(ValueError, match='make_fixtures'): practice_suite(without, source_documents(brief))
    # In a build they replace the kit's customers, are measured on the mock, and are never called official.
    hosts = []
    class OwnBank(FakeFreya):
        def evaluate(self, cases, suite, folder, bank_host=None):
            hosts.append((bank_host, suite.evidence_type, [c['id'] for c in cases]))
            return super().evaluate(cases, suite, folder)
    seen = []
    builder = Builder(Config(artifacts=work, tracing=False), brief, KIT / 'tools/openapi.json', roles_factory=roles(spec, requirements, [], seen), adapter_factory=OwnBank, mock_url=MOCK, cases=path)
    builder.submission_dir = work / 'out'
    result = builder.run()
    assert hosts == [(MOCK, 'generated', ['OWN-01', 'OWN-02'])] and result['evaluation_type'] == 'generated' and result['final_score']['total'] == 2
    assert builder.contracts['operations']['get_account']['url'].startswith(MOCK)
    with pytest.raises(ValueError, match='need a bank'):
        Builder(Config(artifacts=work, tracing=False), brief, KIT / 'tools/openapi.json', roles_factory=roles(spec, requirements, [], []), adapter_factory=FakeFreya, cases=path)


def test_the_command_reports_bad_input_as_one_line(folder, capsys, monkeypatch):
    for name in ('FREYA_API_KEY', 'FREYA_BANK_TEAM_KEY', 'OPENROUTER_API_KEY', 'MODAL_BASE_URL', 'MODAL_KEY', 'MODAL_SECRET', 'DASHSCOPE_API_KEY'):
        monkeypatch.setenv(name, 'fixture-value-0123456789')
    assert main([str(folder), MOCK, MOCK + '/second']) == 2
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {'status': 'invalid_input', 'error': 'More than one mock address given'}


# ------------------------------------------------------------------ a contract with objects inside objects, and a large case

NESTED = {"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "https://bank.example"}], "paths": {
    "/shop/v1/orders.list": {"post": {"operationId": "orders.list", "description": "the customer's orders", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {
        "data": {"type": "object", "required": ["orderNo"], "properties": {"orderNo": {"type": "string"}, "aiFlow": {"type": "string", "enum": ["Shop"]}}},
        "call": {"type": "object", "properties": {"ani": {"type": "string"}, "lang": {"type": "string"}}}}}}}},
        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {
            "data": {"type": "object", "properties": {"orders": {"type": "array", "items": {"type": "object"}}, "exitState": {"type": "string"},
                                                       "debt": {"description": "one block", "allOf": [{"type": "object", "properties": {"amount": {"type": "number"}}}]}}},
            "result": {"type": "object", "properties": {"returnCode": {"type": "string"}}}}}}}}}}}}}


def test_a_nested_request_is_bound_by_field_and_sent_in_its_documented_shape(tmp_path):
    import json
    from builder.contracts import compile_openapi, compile_workflow
    from builder.validation import validate
    path = tmp_path / 'api.json'
    path.write_text(json.dumps(NESTED))
    contracts = compile_openapi(path, server='https://mock.example.workers.dev')
    operation = contracts['operations']['orders_list']          # a service named orders.list is the tool orders_list
    assert operation['url'] == 'https://mock.example.workers.dev/shop/v1/orders.list'
    assert list(operation['body']['properties']) == ['orderNo', 'aiFlow', 'ani', 'lang'] and operation['body']['required'] == ['orderNo']
    assert operation['nest']['orderNo'] == ['data', 'orderNo'] and operation['documented_body']['properties']['data']['type'] == 'object'
    end = {"name": "bye", "node_type": "end_call", "terminal": {"function": {"handler": "__function__:end_call", "parameters": {"properties": {"message_mode": {"default": "none"}}}}}}
    source = {"initial_node": "hello", "system_prompt": "x", "global_nodes": {}, "nodes": {
        "hello": {"name": "hello", "node_type": "conversation", "task_message": "Say hello.", "max_node_turns": 3, "max_turn_transition": "bye",
                  "extraction_schema": [{"name": "r", "type": "string", "enum_values": ["a"], "description": "d", "min_confidence": 0.6}], "transitions": [{"target_node": "list_orders", "condition": {"operator": "always"}}]},
        "list_orders": {"name": "list_orders", "node_type": "api_request", "transitions": [{"target_node": "bye", "condition": {"operator": "always"}}], "pre_actions": [
            {"bank_operation": "orders_list", "description": "CALL when the call starts", "bindings": {"orderNo": "{{orderNumber}}", "aiFlow": "Shop", "lang": "tr"},
             "response_mapping": [{"path": "data.data.orders", "variable": "orders"}, {"path": "data.data.exitState", "variable": "exit_state"}, {"path": "data.data.debt", "variable": "debt"}]}]},
        "bye": end}}
    compiled = compile_workflow(source, contracts)[0]
    tool = compiled['nodes']['list_orders']['pre_actions'][0]
    assert tool['function']['parameters']['properties']['body'] == {"type": "object", "default": {"data": {"orderNo": "{{orderNumber}}", "aiFlow": "Shop"}, "call": {"lang": "tr"}}}
    assert tool['config'] == {"timeoutMs": 30000, "maxRetries": 0}
    assert 'data.orders' in tool['post_process_code']           # the list inside the answer's data reaches code stages
    assert '["debt", "data.debt"]' in tool['post_process_code'] and 'exit_state' not in tool['post_process_code']   # so does an object written as allOf; a text does not
    scope = {'vars': {}, 'result': {'data': {'data': {'orders': [{'a': 1}], 'debt': {'amount': 5.5}, 'exitState': 'x'}}}}
    exec(tool['post_process_code'], scope, scope)
    assert json.loads(scope['vars']['debt']) == {'amount': 5.5} and json.loads(scope['vars']['orders']) == [{'a': 1}]
    assert validate(compiled, contracts)['errors'] == []
    source['nodes']['list_orders']['pre_actions'][0]['bindings'] = {"aiFlow": "Shop"}
    assert any('orderNo' in e for e in validate(compile_workflow(source, contracts)[0], contracts)['errors'])   # a required field without a binding


def test_a_data_file_is_shown_by_its_first_records(tmp_path):
    import json
    from builder.sources import MAX_DATA_CHARS, read_document
    path = tmp_path / 'customers.json'
    path.write_text(json.dumps([{"customer": n, "answer": "x" * 200} for n in range(2000)]))
    text, why = read_document(path)
    assert why is None and len(text) < MAX_DATA_CHARS + 300 and 'more records of the same shape' in text


def test_example_calls_become_test_callers_and_are_scored_from_the_judges_verdict(work):
    tmp_path = work
    from builder.freya_adapter import FreyaAdapter, scenario_suite
    from builder.scoring import score
    suite, cases = scenario_suite([{'id': 'Example 1: one card', 'title': 'One card', 'kind': 'Happy', 'variables': {'orderNumber': 90000001, 'now': '2026-10-12T10:30:00+03:00'},
                                    'persona': 'Yalnızca söylediklerini yaz.', 'checks': ['the debt is read', 'the caller is sent to the main menu']},
                                   {'id': 'no-persona', 'title': '', 'variables': {}, 'persona': ' ', 'checks': ['x']}])
    assert suite.case_ids == ('Example-1-one-card',) and suite.evidence_type == 'generated' and cases[0]['variables']['orderNumber'] == '90000001'
    assert scenario_suite([]) == (None, [])
    messages = [{'role': 'assistant', 'message': 'Borcunuz 5 lira.', 'nodeId': 'read'},
                {'role': 'system', 'nodeId': 'orders', 'message': json.dumps({'event': 'function_call_start', 'function': 'api_call', 'args': {'url': 'https://mock.example/shop/v1/orders.list', 'body': {}}})},
                {'role': 'system', 'nodeId': 'orders', 'message': json.dumps({'event': 'function_call_error', 'function': 'api_call', 'error': 'API request failed: 404'})}]

    class Client:
        def create_personas(self, specs):
            assert specs[0]['prompt'] == 'Yalnızca söylediklerini yaz.' and 'the debt is read' in specs[0]['successCriteria']
            return {'personas': [{'id': 'p1'}]}
        def run_simulation(self, agent, name, variables):
            assert agent == 'agent-1' and variables == {'p1': {'orderNumber': '90000001', 'now': '2026-10-12T10:30:00+03:00'}}
            return 'sim', 'it', 'completed'
        def get_iteration(self, sim, iteration):
            return {'runs': [{'personaId': 'p1', 'outcome': 'fail', 'reason': 'the offer was not made', 'callId': 'c1', 'agentVersionNumber': 3}]}
        def get_call(self, call):
            return {'id': call, 'messages': messages}

    class Quiet:
        redact = staticmethod(lambda value: value)
        def event(self, *a, **k): pass
        def span(self, *a, **k):
            from contextlib import nullcontext
            return nullcontext()
    adapter = FreyaAdapter.__new__(FreyaAdapter)
    adapter.client, adapter.trace, adapter.deployment = Client(), Quiet(), {'agent_id': 'agent-1', 'version': 3}
    adapter.deadline = type('D', (), {'require': lambda self, seconds=0: None})()
    import builder.freya_adapter as module
    kept = module.writable
    module.writable = lambda path: path
    try:
        raw = adapter.evaluate_scenarios(cases, suite, tmp_path / 'evaluation')
    finally:
        module.writable = kept
    row = raw['all_rows'][0][0]
    assert row['pass'] is False and row['failed'] == ['conversation: the offer was not made'] and row['tools'] == ['orders.list']
    record = json.loads((tmp_path / 'evaluation' / 'calls_0.json').read_text())['Example-1-one-card']
    assert record['turns'][-1]['error'] == 'API request failed: 404'       # a failed call is part of what happened
    assert score(raw, suite).passed == 0 and score(raw, suite).complete


def test_a_build_can_go_on_from_the_best_version_of_an_earlier_run(work, spec, requirements, folder):
    given = case([str(folder), MOCK])
    first, result = build(work, spec, requirements, given, [])
    assert result['status'] == 'exported'
    # The earlier run's exported version is where the next one starts: no design call, the same source.
    seen = []
    second, again = build(work, spec, requirements, given, seen, resume=first.root, resume_best=True)
    assert again['status'] == 'exported' and not [role for role, _ in seen if role == 'ADASDesignerAgent']
    resumed = [json.loads(line) for line in Path(again['trace_path']).read_text().splitlines() if '"root_resumed"' in line]
    assert resumed and resumed[0]['best_version'] == result['candidate_id']
    source = lambda run, candidate: json.loads((run.root / 'candidates' / candidate / 'proposal.json').read_text())
    assert source(second, again['root_candidate_id']) == source(first, result['candidate_id'])
    # Without the flag it is the earlier run's first design, as before.
    third, plain = build(work, spec, requirements, given, [], resume=first.root)
    assert 'best_version' not in next(json.loads(line) for line in Path(plain['trace_path']).read_text().splitlines() if '"root_resumed"' in line)
