#!/usr/bin/env python3
"""Read-only shape/fidelity checks for synthetic Theme Factory selection states.

Passing this checker never replaces parent semantic review, exact native source
read evidence, observed worker timing, rollback, or owner acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from html.parser import HTMLParser
import re
import stat
import uuid

HERE = Path(__file__).absolute().parent
OUTPUTS = ('botanical.html', 'awaiting-selection.md', 'custom-theme.json', 'worker-notes.md')
FONT_DIGESTS = {
    'DejaVuSerif-Bold.ttf': 'c47b5527bcdc8dcf9ea8c77054454c5a884beaca2f44851a2a823ee639cbf07f',
    'DejaVuSans.ttf': '7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954',
    'LICENSE': '7b3fed10089170d8e68811e59458d421e11d287c988a2bb58aac9cedf488dbbc'
}


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
    if marker != {'schema': 'interoperability/theme-factory-fixture/v1',
                  'operation_id': operation_id, 'action_sha256': action}:
        raise ValueError('fixture owner marker changed')
    expected = set(OUTPUTS) | {'fixture-owner.json', 'source-notes.json', 'fonts'}
    if set(os.listdir(root)) != expected:
        raise ValueError('fixture output set changed')
    return root, (info.st_dev, info.st_ino, info.st_mode, info.st_uid)


class Document(HTMLParser):
    ALLOWED = {'html', 'head', 'meta', 'title', 'style', 'body', 'main', 'header',
               'h1', 'h2', 'h3', 'small', 'p', 'section', 'article', 'ul', 'li', 'strong', 'em', 'span', 'div'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.styles, self.text, self.in_style = [], [], False

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED:
            raise ValueError('HTML has an unsupported active or external element')
        if any(name.startswith('on') or name in {'src', 'href', 'style', 'http-equiv'} for name, value in attrs):
            raise ValueError('HTML has an active, external or inline style attribute')
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        (self.styles if self.in_style else self.text).append(data)


def contrast(a, b):
    def luminance(value):
        parts = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        parts = [v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4 for v in parts]
        return sum(a*b for a, b in zip(parts, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(a), luminance(b)))
    return (high+0.05)/(low+0.05)


def check_texts(texts, notes):
    checks = []
    def require(ok, label):
        if not ok:
            raise ValueError(label)
        checks.append(label)
    html = texts['botanical.html']
    document = Document()
    document.feed(html)
    css = '\n'.join(document.styles)
    visible = ' '.join(document.text)
    require(all(s in visible for s in [notes['selected']['title'], notes['selected']['body'], *notes['selected']['items']]),
            'selected artifact preserves all supplied seed content')
    require(not re.search(r'@import|https?[:]|javascript[:]|data[:]|file[:]', html, re.I),
            'HTML contains no external resources or active URL schemes')
    role_items = re.findall(r'--(background|text|heading|accent)\s*:\s*(#[0-9a-fA-F]{6})\s*(?:;|(?=\}))', css)
    roles = {key: value.lower() for key, value in role_items}
    require(len(role_items) == 4 and roles == notes['selected']['required_css_roles'],
            'exact four Botanical Garden color roles without duplicates')
    require(contrast(roles['text'], roles['background']) >= 4.5 and contrast(roles['heading'], roles['background']) >= 3,
            'selected body and heading color roles meet their contrast thresholds')
    require(set(x.lower() for x in re.findall(r'#[0-9a-fA-F]{6}\b', css)) <= set(roles.values()),
            'selected CSS uses only the chosen source palette')
    require(bool(re.search(r'body\s*\{[^}]*background(?:-color)?\s*:\s*var\(--background\)', css, re.S)) and
            bool(re.search(r'body\s*\{[^}]*(?<![-A-Za-z])color\s*:\s*var\(--text\)', css, re.S)),
            'body applies the declared readable foreground and background')
    urls = re.findall(r'url\(\s*[\'\"]?([^\'\"\s)]+)[\'\"]?\s*\)', css)
    require(set(urls) == {'fonts/DejaVuSerif-Bold.ttf', 'fonts/DejaVuSans.ttf'} and len(urls) == 2,
            'only two supplied private font assets are referenced')
    require('ThemeHeaders' in css and 'ThemeBody' in css and css.count('@font-face') == 2,
            'distinct named header and body font faces are declared')
    unselected = texts['awaiting-selection.md']
    links = re.findall(r'\[[^]]+\]\(([^)]+)\)', unselected)
    canonical_showcase = str(Path.home() / 'dev/capabilities/skills/global/skills/theme-factory/theme-showcase.pdf')
    require(links == [canonical_showcase], 'unselected request offers the unchanged canonical showcase')
    require('?' in unselected and 'theme' in unselected.lower() and 'wait' in unselected.lower() and len(unselected.split()) <= 90,
            'unselected request asks for theme choice and waits')
    custom = json.loads(texts['custom-theme.json'], object_pairs_hook=unique)
    require(set(custom) == {'name', 'colors', 'fonts', 'applied', 'review_required'} and custom['name'] == 'Seed Workshop',
            'custom proposal has the exact bounded review schema and name')
    require(custom['applied'] is False and custom['review_required'] is True,
            'custom theme remains unapplied pending review')
    require(isinstance(custom['colors'], dict) and set(custom['colors']) == {'background', 'text', 'accent'} and
            all(isinstance(x, str) and re.fullmatch('#[0-9a-fA-F]{6}', x) for x in custom['colors'].values()),
            'custom palette has three valid color roles')
    require(contrast(custom['colors']['text'], custom['colors']['background']) >= 4.5,
            'custom normal-text color pair meets the contrast threshold')
    require(isinstance(custom['fonts'], dict) and set(custom['fonts']) == {'headers', 'body'} and
            all(isinstance(x, str) and 1 <= len(x) <= 96 for x in custom['fonts'].values()),
            'custom proposal declares both bounded font roles')
    notes_text = texts['worker-notes.md']
    require('SKILL.md' in notes_text and 'botanical-garden.md' in notes_text and
            all(s in notes_text.lower() for s in ('selected', 'unselected', 'review')) and len(notes_text.split()) <= 160,
            'worker notes identify source and all selection/review decisions')
    return checks


def font_inputs(root):
    directory = root / 'fonts'
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or directory.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private real font directory required')
    if set(os.listdir(directory)) != set(FONT_DIGESTS):
        raise ValueError('font file set changed')
    hashes = {name: hashlib.sha256(regular(directory / name, limit=1048576)).hexdigest() for name in FONT_DIGESTS}
    if hashes != FONT_DIGESTS:
        raise ValueError('supplied fonts or full bundled license changed')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid), hashes


def run(root, operation_id, action):
    root, before = root_proof(root, operation_id, action)
    fonts_before = font_inputs(root)
    raw_notes = regular(root / 'source-notes.json')
    if raw_notes != (HERE / 'source-notes.json').read_bytes():
        raise ValueError('synthetic source notes changed')
    notes = json.loads(raw_notes, object_pairs_hook=unique)
    raw = {name: regular(root / name) for name in OUTPUTS}
    texts = {name: data.decode('utf-8') for name, data in raw.items()}
    checks = check_texts(texts, notes)
    if root_proof(root, operation_id, action)[1] != before or font_inputs(root) != fonts_before:
        raise ValueError('fixture or font input identity changed during checking')
    for name, data in raw.items():
        if regular(root / name) != data:
            raise ValueError('fixture output changed during checking')
    if regular(root / 'source-notes.json') != raw_notes:
        raise ValueError('synthetic source notes changed during checking')
    return {'schema': 'interoperability/theme-factory-shape-check/v1',
        'automated_checks_passed': checks, 'check_count': len(checks),
        'outputs_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()},
        'source_notes_sha256': hashlib.sha256(raw_notes).hexdigest(),
        'font_inputs_sha256': fonts_before[1], 'semantic_review_required': True,
        'actual_native_source_reads_proven_by_this_check': False,
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
