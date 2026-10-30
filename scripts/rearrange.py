"""Copy-only Codex history repair. Python 3.10+; zstandard for compressed history."""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid


@contextlib.contextmanager
def ro(path):
    c = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@contextlib.contextmanager
def stream(path):
    with path.open('rb') as raw:
        if path.suffix == '.zst':
            try:
                import zstandard
            except ImportError:
                raise RuntimeError('Compressed history requires: python -m pip install zstandard')
            with zstandard.ZstdDecompressor().stream_reader(raw) as z:
                with io.BufferedReader(z) as f:
                    yield f
        else:
            yield raw


def records(path, limit=None):
    with stream(path) as f:
        offset = 0
        for line in f:
            offset += len(line)
            if limit is not None and offset > limit:
                raise ValueError('Inherited cutoff is not a record boundary')
            yield json.loads(line)
            if limit is not None and offset == limit:
                return
        if limit is not None and offset != limit:
            raise ValueError('Inherited cutoff exceeds file')


def metadata(path):
    with stream(path) as f:
        j = json.loads(f.readline())
    if j['type'] != 'session_meta':
        raise ValueError('Expected session_meta: ' + str(path))
    return j


def chain(home, path, seen=None, limit=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError('History inheritance cycle')
    seen.add(path)
    m = metadata(path)['payload']
    base = m.get('history_base')
    if m.get('forked_from_id') and not base:
        raise ValueError('Fork without explicit history_base is unsupported; select the original')
    result = []
    if base:
        key = base['thread_id']
        candidates = [p for p in home.joinpath('sessions').rglob('*' + key + '*')
                      if p.name.endswith(key + '.jsonl') or p.name.endswith(key + '.jsonl.zst')]
        if len(candidates) != 1:
            raise ValueError('Ancestor missing or ambiguous: ' + key)
        result = chain(home, candidates[0], seen, base['end_byte_offset'])
    return result + [(path, limit)]


def stamp(value):
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def insert(c, table, row):
    cols = list(row)
    c.execute('INSERT INTO ' + table + ' (' + ','.join(cols) + ') VALUES (' +
              ','.join('?' for _ in cols) + ')', [row[k] for k in cols])


def capacity(p):
    error = p.get('error')
    msg = error.get('message', '') if isinstance(error, dict) else str(error or '')
    return '429' in msg or 'at capacity' in msg.lower()


def prepare(a):
    home = a.home.resolve()
    with ro(home / 'state_5.sqlite') as c:
        row = c.execute('SELECT * FROM threads WHERE id=?', (a.source,)).fetchone()
        if row is None:
            raise ValueError('Source ID not found')
        source = dict(row)
    new = str(uuid.uuid4())
    bundle = (a.output or home / 'session-rearrange-backups') / new
    bundle.mkdir(parents=True, exist_ok=False)
    backup = bundle / 'original'
    backup.mkdir()
    segments = []
    hashes = []
    for i, (path, limit) in enumerate(chain(home, Path(source['rollout_path']))):
        target = backup / (str(i) + '-' + path.name)
        shutil.copyfile(path, target)
        h = digest(target)
        if h != digest(path):
            raise ValueError('Source changed while copying: ' + str(path))
        hashes.append({'source': str(path), 'copy': str(target), 'sha256': h})
        segments.append((target, limit))
    for name in ('state_5.sqlite', 'thread_history_1.sqlite'):
        with ro(home / name) as src, contextlib.closing(sqlite3.connect(backup / name)) as dst:
            src.backup(dst)
    source_rows = backup / 'thread_history_1.sqlite'
    # Obtain app-native UI item shapes, not guessed conversions from raw event names.
    wanted = set()
    async_ids = set()
    for path, limit in segments:
        for j in records(path, limit):
            p = j.get('payload', {})
            if j['type'] == 'event_msg' and p.get('type') == 'item_completed':
                item = p['item']
                if item.get('id'):
                    wanted.add(item['id'])
                if item.get('delivery') == 'async' or item.get('questions'):
                    async_ids.add(item.get('id'))
    templates = {}
    with ro(source_rows) as c:
        # Other independent copies can hold the same historical item IDs. Source wins.
        for sql, params in [('SELECT * FROM thread_items WHERE thread_id=?', (a.source,)),
                            ('SELECT * FROM thread_items', ())]:
            for r in c.execute(sql, params):
                if r['item_id'] in wanted and r['item_id'] not in templates:
                    templates[r['item_id']] = dict(r)
    projection = sqlite3.connect(bundle / 'projection.sqlite')
    with ro(source_rows) as c:
        for table in ('thread_turns', 'thread_items', 'thread_history_projection_state'):
            sql = c.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
            projection.execute(sql)
    turn_cols = {r[1] for r in projection.execute('PRAGMA table_info(thread_turns)')}
    counts = {'completed_rounds': 0, 'async_questions': len(async_ids), 'capacity_errors': 0,
              'items': 0, 'bookkeeping_extensions': 0}
    current = None
    ordinal = 0
    offset = 0
    ids_written = set()
    start_template = None
    for path, limit in segments:
        for j in records(path, limit):
            if j.get('payload', {}).get('type') == 'task_started':
                start_template = j['payload'].copy()
                break
        if start_template:
            break
    if not start_template:
        raise ValueError('No valid task_started template')
    with (bundle / 'rollout.jsonl').open('wb') as out:
        def emit(j):
            nonlocal ordinal, offset
            if j['type'] != 'session_meta':
                j['ordinal'] = ordinal
                ordinal += 1
            data = (json.dumps(j, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf8')
            out.write(data)
            offset += len(data)
        meta = metadata(segments[-1][0])
        meta['payload'].update(id=new, session_id=new, history_mode='paginated')
        for k in ('history_base', 'forked_from_id'):
            meta['payload'].pop(k, None)
        emit(meta)
        for path, limit in segments:
            for j in records(path, limit):
                p = j.get('payload', {})
                typ = p.get('type')
                if j['type'] == 'session_meta':
                    continue
                if j['type'] == 'event_msg' and typ in ('task_started', 'task_complete', 'turn_aborted'):
                    counts['capacity_errors'] += int(capacity(p))
                    continue
                if j['type'] == 'event_msg' and typ in ('error', 'stream_error') and capacity(p):
                    counts['capacity_errors'] += 1
                    continue
                if current is None:
                    tid = str(uuid.uuid4())
                    ts = stamp(j.get('timestamp'))
                    current = {'thread_id': new, 'turn_id': tid, 'root_turn_id': tid,
                               'rollout_ordinal': ordinal, 'rollout_byte_offset': offset,
                               'status': 'interrupted', 'started_at': ts,
                               'first_user_item_id': None, 'final_agent_item_id': None}
                    start = start_template.copy()
                    start.update(turn_id=tid, root_turn_id=tid, started_at=ts)
                    start.pop('turn_attribution', None)
                    emit({'type': 'event_msg', 'timestamp': j.get('timestamp'), 'payload': start})
                tid = current['turn_id']
                # Only known structural locations; never rewrite nested tool output.
                for k in ('thread_id', 'session_id'):
                    if k in p:
                        p[k] = new
                for location in (p, p.get('turn_attribution', {}),
                                 p.get('internal_chat_message_metadata_passthrough', {})):
                    for k in ('turn_id', 'root_turn_id'):
                        if k in location:
                            location[k] = tid
                item = p.get('item', {}) if typ == 'item_completed' else {}
                iid = item.get('id')
                if iid in async_ids:
                    item['phase'] = 'commentary'
                if p.get('id') in async_ids and typ == 'message':
                    p['phase'] = 'commentary'
                if iid and iid not in ids_written:
                    template = templates.get(iid)
                    if template is None:
                        if item.get('type') != 'Extension':
                            raise ValueError('No native UI projection for item ' + iid)
                        counts['bookkeeping_extensions'] += 1
                    else:
                        r = template.copy()
                        ui = json.loads(r['item_json'])
                        if iid in async_ids:
                            ui['phase'] = 'commentary'
                        ts = stamp(j.get('timestamp'))
                        r.update(thread_id=new, turn_id=tid, rollout_ordinal=ordinal,
                                 item_json=json.dumps(ui, ensure_ascii=False),
                                 created_at_ms=int(ts * 1000) if ts is not None else r['created_at_ms'])
                        if 'updated_at_ordinal' in r:
                            r['updated_at_ordinal'] = ordinal
                        insert(projection, 'thread_items', r)
                        counts['items'] += 1
                        if item.get('type') == 'UserMessage' and not current['first_user_item_id']:
                            current['first_user_item_id'] = iid
                    ids_written.add(iid)
                final = item.get('type') == 'AgentMessage' and item.get('phase') == 'final_answer'
                emit(j)
                if final:
                    end = stamp(j.get('timestamp'))
                    begin = current['started_at']
                    duration = int((end - begin) * 1000) if end is not None and begin is not None and end >= begin else None
                    text = ''.join(x.get('text', '') for x in item.get('content', []))
                    end_ordinal = ordinal
                    emit({'type': 'event_msg', 'timestamp': j.get('timestamp'), 'payload': {
                        'type': 'task_complete', 'turn_id': tid, 'root_turn_id': tid,
                        'last_agent_message': text, 'error': None, 'started_at': begin,
                        'completed_at': end, 'duration_ms': duration}})
                    current.update(status='completed', final_agent_item_id=iid, completed_at=end,
                                   duration_ms=duration, rollout_end_ordinal=end_ordinal,
                                   rollout_end_byte_offset=offset)
                    insert(projection, 'thread_turns', {k: v for k, v in current.items() if k in turn_cols})
                    counts['completed_rounds'] += 1
                    current = None
        if current:
            current.update(rollout_end_ordinal=ordinal - 1, rollout_end_byte_offset=offset)
            insert(projection, 'thread_turns', {k: v for k, v in current.items() if k in turn_cols})
        insert(projection, 'thread_history_projection_state', {
            'thread_id': new, 'next_rollout_byte_offset': offset, 'next_rollout_ordinal': ordinal})
    projection.commit()
    projection.close()
    for h in hashes:
        if digest(Path(h['source'])) != h['sha256']:
            raise ValueError('Source changed during preparation; discard candidate')
    manifest = {'source_id': a.source, 'new_id': new, 'home': str(home), 'title': a.title,
                'source_row': source, 'backups': hashes, 'counts': counts,
                'rollout_sha256': digest(bundle / 'rollout.jsonl'),
                'projection_sha256': digest(bundle / 'projection.sqlite'),
                'ui_verified': False, 'continued_execution_verified': False}
    (bundle / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    verify(bundle)
    print(json.dumps({'bundle': str(bundle), 'new_id': new, 'counts': counts}, ensure_ascii=False))


def verify(bundle):
    m = json.loads((bundle / 'manifest.json').read_text(encoding='utf8'))
    for file, field in [('rollout.jsonl', 'rollout_sha256'), ('projection.sqlite', 'projection_sha256')]:
        if digest(bundle / file) != m[field]:
            raise ValueError('Candidate hash mismatch: ' + file)
    ordinal = 0
    offsets = {}
    offset = 0
    with (bundle / 'rollout.jsonl').open('rb') as f:
        for line in f:
            j = json.loads(line)
            if j['type'] != 'session_meta':
                if j.get('ordinal') != ordinal:
                    raise ValueError('Non-contiguous ordinal')
                p = j.get('payload', {})
                offsets[ordinal] = (offset, offset + len(line), p.get('turn_id'),
                                    p.get('item', {}).get('id'))
                ordinal += 1
            else:
                p = j['payload']
                if p['id'] != m['new_id'] or p.get('history_base') or p.get('forked_from_id'):
                    raise ValueError('Not independent')
            offset += len(line)
    with ro(bundle / 'projection.sqlite') as c:
        for r in c.execute('SELECT * FROM thread_turns'):
            if r['thread_id'] != m['new_id'] or offsets[r['rollout_ordinal']][0] != r['rollout_byte_offset']:
                raise ValueError('Round offset/identity mismatch')
            if r['status'] == 'completed':
                found = c.execute('SELECT item_json FROM thread_items WHERE thread_id=? AND turn_id=? AND item_id=?',
                                  (m['new_id'], r['turn_id'], r['final_agent_item_id'])).fetchone()
                if not found or json.loads(found[0]).get('phase') != 'final_answer':
                    raise ValueError('Completed round without genuine final answer')
            if r['rollout_end_ordinal'] is not None and offsets[r['rollout_end_ordinal']][1] != r['rollout_end_byte_offset']:
                raise ValueError('Round end offset mismatch')
        for r in c.execute('SELECT * FROM thread_items'):
            if r['thread_id'] != m['new_id'] or not c.execute(
                    'SELECT 1 FROM thread_turns WHERE thread_id=? AND turn_id=?',
                    (r['thread_id'], r['turn_id'])).fetchone():
                raise ValueError('Orphan or foreign item')
            raw = offsets[r['rollout_ordinal']]
            if raw[2] != r['turn_id'] or raw[3] != r['item_id']:
                raise ValueError('Item association mismatch')
        p = c.execute('SELECT * FROM thread_history_projection_state').fetchone()
        if p['next_rollout_byte_offset'] != offset or p['next_rollout_ordinal'] != ordinal:
            raise ValueError('Projection cursor mismatch')
        completed = c.execute("SELECT count(*) FROM thread_turns WHERE status='completed'").fetchone()[0]
        if completed != m['counts']['completed_rounds']:
            raise ValueError('Completed-round count mismatch')
    print('Offline validation passed; UI and execution are not validated.')


def install(bundle):
    verify(bundle)
    m = json.loads((bundle / 'manifest.json').read_text(encoding='utf8'))
    home = Path(m['home'])
    new = m['new_id']
    target = home / 'sessions' / dt.datetime.now().strftime('%Y/%m/%d') / ('rollout-copy-' + new + '.jsonl')
    target.parent.mkdir(parents=True, exist_ok=True)
    # One attached-DB transaction scopes all writes to the new ID. No source updates.
    c = sqlite3.connect(home / 'state_5.sqlite', timeout=10)
    c.execute('ATTACH DATABASE ? AS hist', (str(home / 'thread_history_1.sqlite'),))
    c.execute('ATTACH DATABASE ? AS candidate', (str(bundle / 'projection.sqlite'),))
    if target.exists() or c.execute('SELECT 1 FROM threads WHERE id=?', (new,)).fetchone():
        c.close()
        raise ValueError('Copy already registered; refusing overwrite')
    shutil.copyfile(bundle / 'rollout.jsonl', target)
    try:
        c.execute('BEGIN IMMEDIATE')
        row = m['source_row'].copy()
        now = int(dt.datetime.now().timestamp())
        row.update(id=new, rollout_path=str(target), title=m['title'], archived=0, archived_at=None,
                   created_at=now, updated_at=now)
        for k, v in {'name': m['title'], 'attached_thread_parent_id': None, 'is_pinned': 0,
                     'created_at_ms': now * 1000, 'updated_at_ms': now * 1000,
                     'recency_at': now, 'recency_at_ms': now * 1000}.items():
            if k in row:
                row[k] = v
        insert(c, 'threads', row)
        for t in ('thread_turns', 'thread_items', 'thread_history_projection_state'):
            cols = [r[1] for r in c.execute('PRAGMA candidate.table_info(' + t + ')')]
            live = [r[1] for r in c.execute('PRAGMA hist.table_info(' + t + ')')]
            if cols != live:
                raise ValueError('Live schema changed: ' + t)
            fields = ','.join(cols)
            c.execute('INSERT INTO hist.' + t + ' (' + fields + ') SELECT ' + fields + ' FROM candidate.' + t)
        c.commit()
    except BaseException:
        c.rollback()
        target.unlink()
        raise
    finally:
        c.close()
    print(json.dumps({'new_id': new, 'title': m['title'], 'registered': True,
                      'ui_verified': False}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='Snapshot and validate a new copy; no live DB writes')
    p.add_argument('--home', type=Path, default=Path.home() / '.codex')
    p.add_argument('--source', required=True, help='Exact source UUID')
    p.add_argument('--title', required=True)
    p.add_argument('--output', type=Path)
    for name in ('verify', 'install'):
        p = sub.add_parser(name)
        p.add_argument('bundle', type=Path)
    a = parser.parse_args()
    if a.command == 'prepare':
        prepare(a)
    elif a.command == 'verify':
        verify(a.bundle)
    else:
        install(a.bundle)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error) as e:
        print('Stopped: ' + str(e), file=sys.stderr)
        sys.exit(1)
