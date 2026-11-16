#!/usr/bin/env python3
"""Read-only shape/fidelity checks for six synthetic communication outputs.

Passing this checker never replaces parent semantic review, exact native source
read evidence, observed worker timing, rollback, or owner acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

HERE = Path(__file__).absolute().parent
OUTPUTS = ('3p-update.md', 'newsletter.md', 'faq.md', 'announcement.md',
           'clarification.md', 'worker-notes.md')
GUIDES = ('3p-updates.md', 'company-newsletter.md', 'faq-answers.md', 'general-comms.md')


def regular(path, limit=32768):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > limit):
        raise ValueError('private bounded unshared fixture file required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink,
                             s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        opened = os.fstat(fd)
        if fields(before) != fields(opened):
            raise ValueError('fixture file identity changed before read')
        blocks = bytearray()
        while len(blocks) <= limit:
            block = os.read(fd, min(65536, limit + 1 - len(blocks)))
            if not block:
                break
            blocks.extend(block)
        if (len(blocks) > limit or fields(os.fstat(fd)) != fields(opened)
                or fields(path.lstat()) != fields(opened)):
            raise ValueError('fixture file changed or exceeded bound')
        return bytes(blocks)
    finally:
        os.close(fd)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate fixture key')
        value[key] = item
    return value


def root_proof(root, operation_id, action):
    root = root.absolute()
    if str(root) != os.path.normpath(str(root)):
        raise ValueError('normalized fixture root required')
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise ValueError('linked fixture root refused')
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('private operator-owned fixture directory required')
    if str(uuid.UUID(operation_id)) != operation_id or not re.fullmatch('[0-9a-f]{64}', action):
        raise ValueError('exact operation binding required')
    marker = json.loads(regular(root / 'fixture-owner.json'), object_pairs_hook=unique)
    if marker != {'schema': 'interoperability/internal-comms-fixture/v1',
                  'operation_id': operation_id, 'action_sha256': action}:
        raise ValueError('fixture owner marker changed')
    expected = set(OUTPUTS) | {'fixture-owner.json', 'source-notes.json'}
    if set(os.listdir(root)) != expected:
        raise ValueError('fixture output set changed')
    return root, (info.st_dev, info.st_ino, info.st_mode, info.st_uid)


def sentences(text):
    text = re.sub(r'\[[^]]*\]\([^)]*\)', 'source', text)
    return len([s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip()) if s])


def links(text):
    return re.findall(r'https?://[^\s)>]+', text)


def check_texts(texts, notes):
    checks = []
    def require(test, label):
        if not test:
            raise ValueError(label)
        checks.append(label)

    all_text = '\n'.join(texts.values())
    allowed = {r['url'] for r in notes['newsletter_facts']}
    require(set(links(all_text)) <= allowed, 'only supplied synthetic source links')
    require(not any(x in all_text for x in ('<script', '<iframe', '\x00')), 'plain communication data')

    update = [line for line in texts['3p-update.md'].splitlines() if line.strip()]
    require(len(update) == 4, 'strict four-line 3P format')
    require(bool(re.fullmatch(r'\S+ Canopy Tools \(2026-10-26 to 2026-11-01\)', update[0])), '3P team and reporting period')
    for line, label in zip(update[1:], ('Progress', 'Plans', 'Problems')):
        require(line.startswith(label + ': ') and 1 <= sentences(line.split(': ', 1)[1]) <= 3,
                '3P ' + label + ' sentence bound')
    require(len(texts['3p-update.md'].split()) <= 160, '3P concise reading length')
    require('1,008' in update[1] and 'October 30' in update[1], '3P supplied progress metrics')
    require('translation' in update[3].lower() and 'editor' in update[3].lower(), '3P supplied blocker')

    newsletter = texts['newsletter.md']
    bullets = [line[2:] for line in newsletter.splitlines() if line.startswith('- ')]
    require(len(bullets) == 20, 'twenty company-wide newsletter items')
    require(len(re.findall(r'^#{1,3} ', newsletter, re.M)) >= 3, 'newsletter sections')
    require(not re.search(r'^\s+- ', newsletter, re.M), 'newsletter has no granular nested items')
    require(all(sentences(line) <= 2 for line in bullets), 'newsletter bullet sentence bound')
    require(all(len(links(line)) == 1 for line in bullets), 'one official synthetic link per newsletter item')
    require(set(links(newsletter)) == allowed and len(links(newsletter)) == len(allowed), 'every supplied newsletter source used once')
    require(sum(bool(re.search(r'\bwe\b', line, re.I)) for line in bullets) >= 12, 'newsletter collective voice')

    faq = [line for line in texts['faq.md'].splitlines() if line.strip()]
    require(len(faq) == 8, 'four FAQ question and answer pairs')
    for index, expected in enumerate(notes['faq_questions']):
        question, answer = faq[index*2:index*2+2]
        require(question == '- *Question*: ' + expected, 'FAQ supplied question ' + str(index+1))
        require(answer.startswith('- *Answer*: ') and 1 <= sentences(answer[12:]) <= 2,
                'FAQ concise answer ' + str(index+1))
        require(bool(links(answer)), 'FAQ authoritative synthetic source ' + str(index+1))
    require('unconfirmed' in faq[-1].lower() and 'owner' in faq[-1].lower(), 'FAQ uncertainty and official response gate')

    announcement = texts['announcement.md']
    first = next((s for s in announcement.splitlines() if s.strip()), '')
    require('Seed Hub' in first and 'maintenance' in first.lower(), 'announcement main point first')
    require(all(s in announcement for s in ('November 4', '09:00 UTC', '2 minutes', 'save your drafts')), 'announcement supplied facts and action')
    require(len(announcement.split()) <= 160, 'announcement concise audience format')

    clarification = texts['clarification.md'].lower()
    require(all(s in clarification for s in ('audience', 'purpose', 'tone', 'format')) and '?' in clarification,
            'incomplete general request asks for all missing context')
    require(len(clarification.split()) <= 70, 'clarification stays bounded')
    worker_notes = texts['worker-notes.md']
    require(all(name in worker_notes for name in GUIDES), 'worker notes identify all four guidelines')
    require(len(worker_notes.split()) <= 200, 'worker notes stay bounded')
    return checks


def run(root, operation_id, action):
    root, before = root_proof(root, operation_id, action)
    raw_notes = regular(root / 'source-notes.json')
    if raw_notes != (HERE / 'source-notes.json').read_bytes():
        raise ValueError('synthetic source notes changed')
    notes = json.loads(raw_notes, object_pairs_hook=unique)
    raw = {name: regular(root / name) for name in OUTPUTS}
    texts = {name: data.decode('utf-8') for name, data in raw.items()}
    checks = check_texts(texts, notes)
    if root_proof(root, operation_id, action)[1] != before:
        raise ValueError('fixture directory identity changed')
    for name, data in raw.items():
        if regular(root / name) != data:
            raise ValueError('fixture output changed during checking')
    if regular(root / 'source-notes.json') != raw_notes:
        raise ValueError('synthetic source notes changed during checking')
    return {'schema': 'interoperability/internal-comms-shape-check/v1',
        'automated_checks_passed': checks, 'check_count': len(checks),
        'outputs_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()},
        'source_notes_sha256': hashlib.sha256(raw_notes).hexdigest(),
        'semantic_review_required': True, 'actual_native_source_reads_proven_by_this_check': False,
        'worker_timing_or_rollback_proven_by_this_check': False,
        'native_or_retained_accepted': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--action-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.root, args.operation_id, args.action_sha256), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        print(json.dumps({'status': 'refused', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
