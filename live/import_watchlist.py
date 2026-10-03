"""Import the English KOL sheet into the learning watchlist.

The sheet carries two kinds of thing and only one of them belongs here. Handles, names and
follower counts describe *whose writing to learn from*. Contact emails and rate cards describe
*who to do business with*, which is outreach — explicitly out of scope for this system — and is
personal data besides. Only the first kind is read; the contact and price columns are dropped at
the parser, not filtered downstream, so they cannot reach a prompt or an export by accident.

The second sheet (机构建联) is entirely partnership material and is not imported at all.

Run: .venv/bin/python -B live/import_watchlist.py [--apply]
"""
from pathlib import Path
import sys, json, re, zipfile, datetime
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SHEET = ROOT / 'Mango_English_X_Finance_KOL_Final.xlsx'
LEARN_SHEET = 'X金融KOL'

# Read these. Everything else in the row is dropped before it becomes a record.
KEEP = {'A': 'name', 'B': 'handle', 'C': 'platform', 'D': 'url', 'E': 'followers', 'F': 'region'}
DROP_REASON = {
    'G': 'rate card — commercial terms, not writing to learn from',
    'H': 'contact email — personal data, and outreach is out of scope for this system',
}


def read_sheet(path, wanted):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        r = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in r.findall('m:si', NS):
            shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    names = [s.get('name') for s in wb.iter('{%s}sheet' % NS['m'])]
    if wanted not in names:
        raise SystemExit(f'sheet {wanted!r} not found; sheets are {names}')
    idx = names.index(wanted) + 1
    rows = []
    sh = ET.fromstring(z.read(f'xl/worksheets/sheet{idx}.xml'))
    for row in sh.iter('{%s}row' % NS['m']):
        cells = {}
        for c in row.findall('m:c', NS):
            col = re.match(r'[A-Z]+', c.get('r')).group()
            if col not in KEEP:          # dropped here, never held in memory
                continue
            v = c.find('m:v', NS)
            if v is None:
                isx = c.find('m:is', NS)
                val = ''.join(x.text or '' for x in isx.iter('{%s}t' % NS['m'])) if isx is not None else ''
            else:
                val = shared[int(v.text)] if c.get('t') == 's' else v.text
            cells[KEEP[col]] = (val or '').strip()
        if cells:
            rows.append(cells)
    return rows


HANDLE = re.compile(r'^@?([A-Za-z0-9_]{1,15})$')


def normalise(rows):
    out, skipped = [], []
    for r in rows[1:]:
        h = (r.get('handle') or '').strip()
        m = HANDLE.match(h)
        if not m:
            url = r.get('url') or ''
            m2 = re.search(r'(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})', url)
            if not m2:
                skipped.append({'name': r.get('name'), 'handle': h, 'why': 'no usable handle'})
                continue
            m = m2
        try:
            fol = int(re.sub(r'[^\d]', '', r.get('followers') or '') or 0)
        except ValueError:
            fol = 0
        out.append({'handle': m.group(1), 'name': r.get('name'),
                    'followers': fol, 'region': r.get('region'),
                    'lang': 'en', 'in_corpus': False,
                    'role': 'style_and_knowledge_learning_only',
                    'source': 'Mango_English_X_Finance_KOL_Final.xlsx / X金融KOL'})
    return out, skipped


def main():
    apply_ = '--apply' in sys.argv
    rows = read_sheet(SHEET, LEARN_SHEET)
    people, skipped = normalise(rows)

    src_path = ROOT / 'live/sources.json'
    src = json.loads(src_path.read_text())
    have = {a['handle'].lower() for a in src['x_accounts']}
    new = [p for p in people if p['handle'].lower() not in have]
    dupes = [p['handle'] for p in people if p['handle'].lower() in have]

    report = {
        'read_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'sheet': SHEET.name, 'sheet_tab': LEARN_SHEET,
        'rows_in_sheet': len(rows) - 1,
        'usable_handles': len(people), 'already_watched': dupes,
        'new_handles': len(new), 'skipped': skipped,
        'columns_read': list(KEEP.values()),
        'columns_dropped_at_parse': DROP_REASON,
        'other_sheet_not_imported': {
            'name': '机构建联',
            'why': 'partnership and sponsorship contacts; this system does not do outreach',
        },
        'followers_range': [min((p['followers'] for p in people), default=0),
                            max((p['followers'] for p in people), default=0)],
    }
    (ROOT / 'live/store/watchlist_import.json').write_text(
        json.dumps({**report, 'handles': [p['handle'] for p in people]},
                   ensure_ascii=False, indent=2))

    if apply_:
        src['learning_accounts'] = new
        src['learning_accounts_note'] = (
            '来自英文 KOL 表，仅用于语言与知识学习：这些账号不是既有语料 donor，'
            '采集后先建风格区间，人工确认前不直接作为某个账号的 language donor')
        src_path.write_text(json.dumps(src, ensure_ascii=False, indent=2))

    print(f"表内 {report['rows_in_sheet']} 行 · 可用 handle {len(people)} · 新增 {len(new)}")
    print(f"已在监控中: {dupes or '无'}")
    print(f"跳过: {len(skipped)}")
    for s in skipped[:5]:
        print(f"   {s['name']} — {s['why']}")
    print(f"解析时即丢弃的列: {list(DROP_REASON.values())}")
    print(f"粉丝数范围: {report['followers_range'][0]:,} – {report['followers_range'][1]:,}")
    print(f"{'已写入 live/sources.json' if apply_ else '未写入（加 --apply 生效）'}")
    return report


if __name__ == '__main__':
    main()
