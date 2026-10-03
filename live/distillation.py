"""Translation-first pipeline. One source, one account, no brief and no merge.

Artifacts are append-only attempts; only QA-passing text is returned as draft text.
Model review is labeled model_reviewed. Human approval is never fabricated.
"""
from __future__ import annotations
import json
from pathlib import Path
import uuid
import fcntl
from live import distillation_prompts as prompts
from live.distillation_client import RelayClient
from live.distillation_source import digest, now, paragraphs, snapshot, source_record
from live.language_support import DEFAULT as DEFAULT_LANGUAGES
from live.domain_policy import policies,account_domain
from live.model_json import parse_object
from live import source_hygiene as hygiene

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'localization_v1.2-hygiene'
DEFAULT_STORE = ROOT / 'live/store/distillation'
LANGUAGES = DEFAULT_LANGUAGES.codes  # compatibility export, not an orchestration enum
CHECKS = ('facts_preserved', 'numeric_bindings_preserved', 'entities_preserved',
          'reasoning_preserved', 'stance_preserved', 'identity_preserved',
          'no_unsupported_additions', 'natural_language', 'minimal_edits',
          'order_emphasis_rhythm_preserved', 'no_editorial_commentary')


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def accounts_from_file(path=ROOT / 'live/accounts.json'):
    return json.loads(Path(path).read_text())['accounts']


def account_profiles(accounts,languages=DEFAULT_LANGUAGES,domain_policies=None):
    available=domain_policies if domain_policies is not None else policies()
    profiles = []
    for row in accounts:
        if row.get('enabled') is not True:
            continue
        require(row.get('lang') in languages.codes, 'enabled account language is not configured/supported')
        require(row.get('id') and row['id'] != 'NONE', 'invalid account id')
        profile = {k: row.get(k) for k in ('id', 'name', 'persona_id', 'lang', 'beats', 'audience', 'platform',
                                           'selection_scope', 'glossary', 'localization_preferences',
                                           'source_preferences','editorial_preferences','source_hygiene','persona_description')}
        profile['domain']=account_domain(row)
        policy_id=row.get('fidelity_policy') or profile['domain']
        require(policy_id in available,'Unknown domain policy; explicitly configure one or choose generic')
        profile.update(fidelity_policy=policy_id,domain_policy_version=available[policy_id].fingerprint)
        profile['profile_version'] = digest(profile)
        profiles.append(profile)
    require(len({r['id'] for r in profiles}) == len(profiles), 'duplicate account ids')
    return profiles


def segments(value, selected):
    rows = value.get('segments')
    require(isinstance(rows, list), 'segments must be a list')
    require([r.get('paragraph_id') for r in rows if isinstance(r, dict)] ==
            [p['paragraph_id'] for p in selected], 'segment alignment is missing, reordered or invalid')
    require(all(isinstance(r.get('text'), str) and r['text'].strip() for r in rows), 'empty translation segment')
    return rows


def text_and_alignment(rows, selected):
    cursor, alignment = 0, []
    for row, source in zip(rows, selected):
        end = cursor + len(row['text'])
        alignment.append({'paragraph_id': row['paragraph_id'],
                          'source_start': source['start'], 'source_end': source['end'],
                          'target_start': cursor, 'target_end': end})
        cursor = end + 2
    return '\n\n'.join(r['text'] for r in rows), alignment


def apply_localization_edits(value, translated, selected, title=''):
    """Apply exact span edits against the frozen translation; never accept a new body.

    Unique quoted spans avoid asking a model to count Unicode offsets. Code computes
    offsets for the private ledger and copies every untouched character verbatim.
    Semantic necessity still requires QA; a valid replacement is not proof of quality.
    """
    require(set(value) == {'edits', 'added_background'},
            'localization accepts only an edit log, not regenerated segments or prose')
    require(value['added_background'] == [], 'External factual additions disabled in v1')
    require(isinstance(value['edits'], list), 'edit log missing')
    originals = {p['paragraph_id']: p['exact_text'] for p in selected}
    texts = {p['paragraph_id']: p['text'] for p in translated}
    by_paragraph = {pid: [] for pid in texts}
    for edit in value['edits']:
        require(isinstance(edit, dict) and set(edit) ==
                {'paragraph_id', 'before', 'after', 'reason', 'source_support'}, 'invalid span edit schema')
        require(all(isinstance(v, str) for v in edit.values()), 'span edit fields must be strings')
        pid, before, after = edit['paragraph_id'], edit['before'], edit['after']
        require(pid in texts, 'edit references unknown paragraph')
        require(bool(before) and before != after, 'empty or unchanged edit span')
        start = texts[pid].find(before)
        require(start >= 0 and texts[pid].find(before, start + 1) < 0,
                'edit span missing or ambiguous in original translation')
        support = edit['source_support']
        require(edit['reason'].strip() and support.strip() and
                (support in originals[pid] or support in title), 'edit lacks exact source support')
        by_paragraph[pid].append({**edit, 'translation_start': start, 'translation_end': start + len(before)})
    localized, ledger = [], []
    for row in translated:
        cursor, pieces = 0, []
        for edit in sorted(by_paragraph[row['paragraph_id']], key=lambda e: e['translation_start']):
            require(edit['translation_start'] >= cursor, 'overlapping localization edits')
            pieces.extend([row['text'][cursor:edit['translation_start']], edit['after']])
            cursor = edit['translation_end']
            ledger.append(edit)
        pieces.append(row['text'][cursor:])
        text = ''.join(pieces)
        require(text.strip(), 'localization removed an entire paragraph')
        localized.append({'paragraph_id': row['paragraph_id'], 'text': text})
    return localized, ledger


class Pipeline:
    pipeline_mode = 'localization_v1'
    pipeline_version = VERSION
    prompt_version = prompts.VERSION + '+' + hygiene.VERSION

    def __init__(self, store=DEFAULT_STORE, accounts=None, client=None, languages=DEFAULT_LANGUAGES, domain_policies=()):
        self.store = Path(store)
        self.store.mkdir(parents=True, exist_ok=True)
        self.languages=languages;self.policies=policies(domain_policies)
        self.accounts = account_profiles(accounts if accounts is not None else accounts_from_file(),languages,self.policies)
        self.account_version = digest(self.accounts)
        self.client = client or RelayClient(self.store / 'calls')

    def key(self, source):
        return digest([self.pipeline_version, self.prompt_version, source['source_version'], self.account_version,self.languages.version])

    def normalize_source(self,row):return source_record(row,self.languages)

    def policy(self,account):return self.policies[account['fidelity_policy']]

    def previous(self, source):
        path = self.store / 'completed' / (self.key(source) + '.json')
        return json.loads(path.read_text()) if path.exists() else None

    def ask(self, attempt, stage, system, payload, max_tokens):
        attempt['stage'] = stage
        attempt['stage_calls'][stage] = attempt['stage_calls'].get(stage, 0) + 1
        account=next((a for a in self.accounts if a['id']==attempt.get('account_id')),None)
        if account:
            policy=self.policy(account)
            if policy.review_guidance:system+='\n\n'+policy.review_guidance
            attempt['domain_policy']={'id':policy.id,'version':policy.version,'fingerprint':policy.fingerprint}
            if hygiene.enabled(account):
                if stage == 'editorial':system+='\n\n'+hygiene.editorial_prompt()
                elif stage in ('translation','localization','adaptation','repair','qa','identity_qa'):
                    system+='\n\n'+hygiene.WRITER_BOUNDARY
                payload={**payload,'source_hygiene_decisions':attempt.get('hygiene_decisions',[]),
                         'source_hygiene_annotations':attempt.get('hygiene_annotations',[])}
        messages = [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        response = self.client(stage, messages, max_tokens)
        attempt['model_responses'].append({'stage': stage, **response})
        require(response.get('finish_reason') == 'stop', f'{stage}: incomplete/unknown finish_reason')
        require(not response.get('refusal'), f'{stage}: model refusal')
        value = parse_object(response.get('text', ''))
        require(isinstance(value, dict), f'{stage}: expected JSON object')
        return value

    def route(self, source, attempt):
        eligible = [r for r in self.accounts if r['lang'] != source['source_language'] and hygiene.eligible(r,source)]
        exclusive=[r for r in eligible if (r.get('source_preferences') or {}).get('exclusive_source') is True]
        if exclusive:eligible=exclusive
        # V1 explicitly enables only cross-language routes. No implicit same-language fallback.
        route = self.ask(attempt, 'routing', prompts.ROUTE,
                         {'source': source, 'eligible_accounts': eligible}, 1000)
        decision = route.get('decision')
        require(decision in {'MOVE', 'SKIP', 'NONE', 'NEEDS_REVIEW', 'NEEDS_SOURCE'}, 'invalid route decision')
        require(type(route.get('worth_moving')) is bool, 'worth_moving must be boolean')
        require(isinstance(route.get('reason'), str) and route['reason'].strip(), 'route requires reason')
        confidence = route.get('confidence')
        require(type(confidence) in (float, int) and 0 <= confidence <= 1, 'invalid route confidence')
        if decision != 'MOVE':
            require(route.get('account_id') is None, 'non-MOVE route must not contain an account')
            require(route.get('target_language') is None, 'non-MOVE route must not contain a language')
            if decision == 'NONE':
                require(route['worth_moving'], 'NONE requires worthwhile but unsuitable content')
            if decision == 'SKIP':
                require(not route['worth_moving'], 'SKIP contradicts worth_moving')
            return {**route, 'target_language': None, 'account_profile_version': None}, None
        require(route['worth_moving'], 'MOVE contradicts worth_moving')
        matches = [r for r in eligible if r['id'] == route.get('account_id')]
        require(len(matches) == 1, 'MOVE account not enabled/eligible')
        account = matches[0]
        require(route.get('target_language', account['lang']) == account['lang'], 'model tried to override account language')
        route.update(target_language=account['lang'], account_profile_version=account['profile_version'])
        # Self-reported scores are uncalibrated diagnostics. Uncertainty must be an
        # explicit NEEDS_REVIEW decision, not an invented universal score cutoff.
        return route, account

    def select(self, source, account, attempt):
        spans = paragraphs(source['original_text'])
        require(bool(spans), 'empty source')
        if len(source['original_text']) <= 1800:
            choice = {'paragraph_ids': [p['paragraph_id'] for p in spans],
                      'reason': 'Short source: preserve whole post', 'dependencies_complete': True,
                      'needs_source': False}
        else:
            choice = self.ask(attempt, 'selection', prompts.SELECT,
                              {'source': source, 'paragraphs': spans, 'account': account}, 1800)
        require(choice.get('needs_source') is False, 'selection requires missing source')
        require(choice.get('dependencies_complete') is True, 'selection dependencies uncertain')
        ids = choice.get('paragraph_ids')
        require(isinstance(ids, list) and ids, 'empty selection')
        chosen = [p for p in spans if p['paragraph_id'] in ids]
        require([p['paragraph_id'] for p in chosen] == ids, 'selection contains unknown/duplicate/reordered paragraph ids')
        for p in chosen:
            require(p['exact_text'] == source['original_text'][p['start']:p['end']], 'source offset mismatch')
        selection = {'source_hash': source['source_hash'], 'passages': chosen,
                     'reason': choice.get('reason'),
                     'excluded_ranges': [{'start': p['start'], 'end': p['end'], 'paragraph_id': p['paragraph_id']}
                                         for p in spans if p['paragraph_id'] not in ids]}
        # Rationale wording is not content identity; rerouting must not defeat dedup.
        selection['selection_id'] = digest([source['source_hash'],
            [(p['paragraph_id'], p['start'], p['end']) for p in chosen]])
        return selection

    def prepare_hygiene(self, source, account, selection, attempt):
        if not hygiene.enabled(account):return True
        annotations=hygiene.selected_annotations(source['source_hygiene'],selection)
        attempt['hygiene_annotations']=annotations
        if not annotations:
            attempt['hygiene_decisions']=[];return True
        value=attempt.get('editorial_judgment',{}).get('hygiene_decisions')
        if value is None:
            result=self.ask(attempt,'source_hygiene',prompts.DATA_RULE+'\n'+hygiene.editorial_prompt(),
                {'source':source,'selected_passages':selection['passages'],'annotations':annotations,'target_account':account},4500)
            value=result.get('hygiene_decisions')
        try:attempt['hygiene_decisions']=hygiene.validate_decisions(value,annotations)
        except ValueError as exc:raise ContractError(str(exc)) from exc
        if any(d['action']=='needs_context' for d in value):
            attempt.update(draft_status='needs_source',why='Editorial source hygiene requires missing context')
            return False
        return True

    def run(self, row, replay=True):
        # Serialize this source/config version across processes, including replay check.
        # Different sources may still run independently.
        source = self.normalize_source(row)
        locks = self.store / 'locks'
        locks.mkdir(exist_ok=True)
        with (locks / (self.key(source) + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._run(row, replay)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _run(self, row, replay=True):
        source = self.normalize_source(row)
        prior = self.previous(source) if replay else None
        if prior:
            # No model invocation and no second draft. Record the replay itself.
            trace = self.store / 'replays'
            trace.mkdir(exist_ok=True)
            (trace / (uuid.uuid4().hex + '.json')).write_text(json.dumps(
                {'at': now(), 'source_version': source['source_version'], 'prior_attempt': prior['attempt_ref']}))
            return {**prior, 'replayed': True}
        attempt = {'run_id': uuid.uuid4().hex, 'pipeline_mode': self.pipeline_mode,
                   'pipeline_version': self.pipeline_version, 'prompt_version': self.prompt_version,
                   'created_at': now(), 'source': source, 'source_ref': snapshot(source, self.store / 'sources'),
                   'source_language': source['source_language'], 'account_id': None, 'target_language': None,
                   'draft_id': None, 'text': '', 'draft_status': 'blocked', 'qa_status': 'not_run',
                   'review_status': 'pending', 'human_review': None, 'stage': 'source',
                   'stage_calls': {}, 'model_responses': [], 'why': ''}
        try:
            unresolved = (source.get('recovery') or {}).get('unresolved', [])
            if not source['content_complete'] or source['media_dependencies'] or any(r.get('required') is True for r in unresolved):
                attempt.update(draft_status='needs_source', why='Full source or required media/context unavailable',
                               source_requirements=unresolved or source['media_dependencies'])
                return self.finish(attempt)
            if source['source_language'] not in self.languages.codes or source['language_confidence'] < .8:
                attempt.update(draft_status='needs_review', why='Unknown or uncertain source language')
                return self.finish(attempt)
            if len(source['original_text']) > 60000:
                attempt.update(draft_status='needs_review', why='Source exceeds v1 context limit; never silently clipped')
                return self.finish(attempt)
            route, account = self.route(source, attempt)
            attempt['route'] = route
            if route['decision'] != 'MOVE':
                attempt.update(draft_status={'SKIP': 'skipped', 'NONE': 'not_suitable',
                                             'NEEDS_SOURCE': 'needs_source', 'NEEDS_REVIEW': 'needs_review'}[route['decision']],
                               why=route['reason'])
                return self.finish(attempt)
            attempt.update(account_id=account['id'], target_language=account['lang'],
                           persona=account.get('persona_id'), account_profile_version=account['profile_version'],
                           account_profile=account)
            selection = self.select(source, account, attempt)
            attempt['selection'] = selection
            if selection.get('needs_source') is True:
                attempt.update(draft_status='needs_source', why=selection.get('reason') or 'Selection requires more context')
                return self.finish(attempt)
            if not self.prepare_hygiene(source,account,selection,attempt):return self.finish(attempt)
            if not self.compose_and_review(source, account, selection, attempt):
                return self.finish(attempt)
            text = attempt['localization']['text']
            attempt.update(draft_status='draft_ready', qa_status='model_reviewed', text=text,
                           draft_version=digest(text),
                           draft_id=digest([self.pipeline_version, source['source_hash'], selection['selection_id'],
                                            account['profile_version']])[:24],
                           why='Fidelity checks passed; human review pending')
        except Exception as exc:
            attempt.update(draft_status='blocked', text='', draft_id=None,
                           why=f'{attempt["stage"]}: {type(exc).__name__}',
                           error_detail=str(exc) if isinstance(exc, (ContractError, json.JSONDecodeError)) else None)
            if getattr(exc,'retry_requires_external_change',False):
                attempt['external_block']='provider_quota'
        return self.finish(attempt)

    def compose_and_review(self, source, account, selection, attempt):
        selected = selection['passages']
        payload = {'source_language': source['source_language'], 'target_language': account['lang'],
                   'author_name': source['author_name'], 'source_title': source['title'],
                   'glossary': {**(account.get('glossary') or {}), **source['entity_glossary']},
                   'selected_passages': selected}
        token_limit = min(14000, max(1800, len(json.dumps(selected, ensure_ascii=False)) * 2))
        value = self.ask(attempt, 'translation', prompts.TRANSLATE, payload, token_limit)
        translated = segments(value, selected)
        text, alignment = text_and_alignment(translated, selected)
        translation = {'translation_id': digest([selection['selection_id'], account['lang'], text]),
                       'source_hash': source['source_hash'], 'selection_id': selection['selection_id'],
                       'target_language': account['lang'], 'segments': translated, 'text': text, 'alignment': alignment}
        attempt['translation'] = translation
        value = self.ask(attempt, 'localization', prompts.LOCALIZE,
                         {**payload, 'translation': translation,
                          'preferences': account.get('localization_preferences') or {}}, token_limit * 2)
        localized, edits = apply_localization_edits(value, translated, selected, source['title'])
        text, alignment = text_and_alignment(localized, selected)
        attempt['localization'] = {'text': text, 'segments': localized, 'alignment': alignment,
                                   'edits': edits, 'added_background': []}
        checks_for_domain=self.policy(account).deterministic
        findings = checks_for_domain(source, selected, translated, account['lang'], 'translation',detector=self.languages.detect)
        findings += checks_for_domain(source, selected, localized, account['lang'], 'localization',detector=self.languages.detect)
        attempt['qa'] = {'method': 'deterministic + model bilingual comparison', 'findings': findings,
                         'human_status': 'pending', 'semantic_status': 'not_run'}
        if findings:
            attempt.update(qa_status='failed', why='Deterministic fidelity checks failed')
            return False
        verdict = self.ask(attempt, 'qa', prompts.QA,
                           {'source': source, 'selection': selection, 'translation': translation,
                            'localization': attempt['localization'], 'target_language': account['lang']}, 6500)
        attempt['qa'].update(semantic=verdict, semantic_status='model_reviewed')
        checks = verdict.get('checks')
        require(isinstance(checks, list) and [c.get('paragraph_id') for c in checks] ==
                [p['paragraph_id'] for p in selected], 'QA did not review every selected paragraph')
        require(all(all(type(c.get(k)) is bool for k in CHECKS) and c.get('evidence') for c in checks),
                'QA missing required dimensions/evidence')
        require(type(verdict.get('confidence')) in (int, float) and 0 <= verdict['confidence'] <= 1, 'invalid QA confidence')
        require(type(verdict.get('selection_context_complete')) is bool, 'QA missing selection assessment')
        require(isinstance(verdict.get('findings'), list), 'QA missing findings')
        # Findings must cite real locations, including omission and addition cases.
        source_text = source['original_text']
        for finding in verdict['findings']:
            require(isinstance(finding, dict) and finding.get('code') and finding.get('detail'), 'invalid QA finding')
            require(finding.get('stage') in ('selection', 'translation', 'localization'), 'invalid QA stage')
            require(finding.get('status') in ('open', 'resolved', 'metadata_note'), 'invalid QA finding status')
            require(finding['status'] != 'resolved' or finding['stage'] == 'translation',
                    'only intermediate translation defects can be resolved')
            require(finding['status'] != 'metadata_note' or finding['stage'] == 'selection',
                    'only editorial selection metadata may be non-blocking notes')
            require(finding.get('paragraph_id') in {p['paragraph_id'] for p in selected}, 'unknown QA paragraph')
            quote = finding.get('source_quote', '')
            require(isinstance(quote, str) and (not quote or quote in source_text), 'QA invented source quotation')
            output = finding.get('output_quote', '')
            require(isinstance(output, str) and (not output or output in translation['text'] or output in text),
                    'QA invented output quotation')
        passed = (verdict['selection_context_complete'] and
                  not any(f['status'] == 'open' for f in verdict['findings']) and
                  all(all(c[k] for k in CHECKS) for c in checks))
        attempt['qa']['findings'] += verdict['findings']
        if not passed:
            attempt.update(draft_status='needs_review', qa_status='failed_or_uncertain', why='Semantic fidelity review did not pass')
            return False
        return True

    def finish(self, attempt):
        account=next((a for a in self.accounts if a['id']==attempt.get('account_id')),None)
        candidate=(attempt.get('localization') or {}).get('text','')
        if account and hygiene.enabled(account) and candidate:
            attempt['hygiene_review']=hygiene.postcheck(attempt['source'],candidate,
                (attempt.get('editorial_judgment') or {}).get('guidance',''),attempt.get('hygiene_decisions',[]))
            if attempt['draft_status']=='draft_ready' and attempt['hygiene_review']['requires_review']:
                attempt.update(draft_status='needs_review',text='',draft_id=None,
                    why='Machine fidelity completed; source-hygiene risks require human review')
        attempt['finished_at'] = now()
        path = self.store / 'attempts' / (attempt['run_id'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        attempt['attempt_ref'] = str(path)
        path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2))
        if attempt['draft_status'] in ('draft_ready', 'skipped', 'not_suitable', 'needs_source'):
            index = self.store / 'completed' / (self.key(attempt['source']) + '.json')
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(json.dumps(attempt, ensure_ascii=False, indent=2))
        return attempt


def comparison_rows(result):
    """Review mapping supports both literal alignment and editorial many-to-many paragraphs."""
    selected = (result.get('selection') or {}).get('passages', [])
    localized = (result.get('localization') or {}).get('segments', [])
    if result.get('editorial_judgment'):
        return [{'paragraph_id': row['paragraph_id'],
                 'source': '\n\n'.join(p['exact_text'] for p in selected if p['paragraph_id'] in row['source_paragraph_ids']),
                 'source_paragraph_ids': row['source_paragraph_ids'], 'translation': '', 'localization': row['text']}
                for row in localized]
    return [{'paragraph_id': p['paragraph_id'], 'source': p['exact_text'],
             'translation': next((r['text'] for r in (result.get('translation') or {}).get('segments', [])
                                  if r['paragraph_id'] == p['paragraph_id']), ''),
             'localization': next((r['text'] for r in localized if r['paragraph_id'] == p['paragraph_id']), '')}
            for p in selected]


def review_markdown(result):
    lines = [f"Account: {result.get('account_id')} | {result.get('source_language')} → {result.get('target_language')}",
             f"Status: {result['draft_status']} | Human: {result['review_status']}", '',
             f"Source: {result['source'].get('author_name')} | {result['source'].get('url')}", '']
    if result.get('editorial_judgment'):
        lines.extend(['### Private editorial judgment', '', result['editorial_judgment'].get('guidance', ''), '',
                      '### Selected original', ''])
        for p in (result.get('selection') or {}).get('passages', []):
            lines.extend([f"**{p['paragraph_id']} [{p['start']}:{p['end']}]**", '', p['exact_text'], ''])
        lines.extend(['### Candidate (may be held by QA)', '', result.get('localization', {}).get('text', ''), '',
                      '### Ready draft output', '', '```text', result.get('text', ''), '```', '',
                      '### Private QA', '', json.dumps(result.get('qa'), ensure_ascii=False, indent=2), ''])
        return '\n'.join(lines)
    for p in (result.get('selection') or {}).get('passages', []):
        pid = p['paragraph_id']
        lines.extend([f"### {pid} · source [{p['start']}:{p['end']}]", '', p['exact_text'], ''])
        for key in ('translation', 'localization'):
            seg = next((s['text'] for s in (result.get(key) or {}).get('segments', []) if s['paragraph_id'] == pid), '')
            lines.extend([f'**{key}**', '', seg, ''])
    lines.extend(['### Exact draft output', '', '```text', result.get('text', ''), '```', '',
                  f"Reason: {result['why']}", '', 'Edits: ' + json.dumps((result.get('localization') or {}).get('edits', []), ensure_ascii=False)])
    return '\n'.join(lines) + '\n'


def export(result, directory):
    """Public body and private provenance are always separate files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'body.txt').write_text(result.get('text', ''), encoding='utf-8')
    (directory / 'metadata.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (directory / 'review.md').write_text(review_markdown(result), encoding='utf-8')
