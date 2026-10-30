"""Isolated integration test; never touches the user's real session databases."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('repair', Path(__file__).with_name('rearrange.py'))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class Integration(unittest.TestCase):
    def test_copy_rounds_projection_and_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / 'sessions'
            sessions.mkdir()
            source = 'source'
            c = sqlite3.connect(home / 'state_5.sqlite')
            c.execute('CREATE TABLE threads (id TEXT PRIMARY KEY,rollout_path TEXT,title TEXT,archived INT,archived_at INT,created_at INT,updated_at INT)')
            c.close()
            c = sqlite3.connect(home / 'thread_history_1.sqlite')
            c.executescript('''
CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,rollout_ordinal INT,status TEXT,started_at INT,completed_at INT,duration_ms INT,first_user_item_id TEXT,final_agent_item_id TEXT,rollout_byte_offset INT,rollout_end_ordinal INT,rollout_end_byte_offset INT,root_turn_id TEXT,PRIMARY KEY(thread_id,turn_id));
CREATE TABLE thread_items(thread_id TEXT,turn_id TEXT,item_id TEXT,rollout_ordinal INT,created_at_ms INT,item_json TEXT,item_type TEXT,updated_at_ordinal INT,PRIMARY KEY(thread_id,turn_id,item_id));
CREATE TABLE thread_history_projection_state(thread_id TEXT PRIMARY KEY,next_rollout_byte_offset INT,next_rollout_ordinal INT);
''')
            def event(kind, **kw):
                return {'timestamp': '2026-10-30T10:00:00Z', 'type': 'event_msg',
                        'payload': dict(type=kind, turn_id='old-turn', thread_id=source, **kw)}
            def item(i, kind, **kw):
                ui = dict(id=i, type={'AgentMessage': 'agentMessage', 'UserMessage': 'userMessage',
                                     'FileChange': 'fileChange'}[kind], **kw)
                c.execute('INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)',
                          (source, 'old-turn', i, 0, 0, json.dumps(ui), ui['type'], 0))
                return event('item_completed', item=dict(id=i, type=kind, **kw))
            records = [
                {'type': 'session_meta', 'payload': {'id': source}},
                event('task_started', started_at=1, model_context_window=100, collaboration_mode_kind='default'),
                item('user', 'UserMessage', content=[{'type': 'Text', 'text': '中文请求429保留'}]),
                item('diff', 'FileChange', changes=[]),
                item('question', 'AgentMessage', phase='final_answer', delivery='async', questions=[{'title': '继续？'}]),
                event('task_complete', error={'message': '429 at capacity'}),
                event('error', error={'message': '500 unrelated error retained'}),
            ]
            ancestor = sessions / 'rollout-ancestor.jsonl'
            ancestor.write_bytes(b''.join((json.dumps(j, ensure_ascii=False) + '\n').encode() for j in records))
            cutoff = ancestor.stat().st_size
            with ancestor.open('ab') as f:
                f.write((json.dumps(event('task_complete', error={'message': 'at capacity discarded branch'})) + '\n').encode())
            latest = sessions / 'rollout-source.jsonl'
            tail = [
                {'type': 'session_meta', 'payload': {'id': source, 'history_base': {'thread_id': 'ancestor', 'end_byte_offset': cutoff}}},
                item('final', 'AgentMessage', phase='final_answer', content=[{'type': 'Text', 'text': '完成'}]),
                item('tail', 'UserMessage', content=[{'type': 'Text', 'text': '未回答'}]),
            ]
            latest.write_text(''.join(json.dumps(j, ensure_ascii=False) + '\n' for j in tail), encoding='utf8')
            c.commit()
            c.close()
            c = sqlite3.connect(home / 'state_5.sqlite')
            c.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?)', (source, str(latest), 'original', 0, None, 1, 1))
            c.commit()
            c.close()
            before = {p: repair.digest(p) for p in (ancestor, latest)}
            repair.prepare(SimpleNamespace(home=home, source=source, title='copy', output=home / 'bundles'))
            bundle = next((home / 'bundles').iterdir())
            m = json.loads((bundle / 'manifest.json').read_text(encoding='utf8'))
            self.assertIn('500 unrelated error retained', (bundle / 'rollout.jsonl').read_text(encoding='utf8'))
            self.assertEqual(m['counts']['completed_rounds'], 1)
            self.assertEqual(m['counts']['async_questions'], 1)
            self.assertEqual(m['counts']['capacity_errors'], 1)
            c = sqlite3.connect(bundle / 'projection.sqlite')
            rows = c.execute('SELECT item_id,turn_id,item_json FROM thread_items').fetchall()
            self.assertEqual(len({r[1] for r in rows if r[0] in ('user', 'diff', 'question', 'final')}), 1)
            self.assertEqual(json.loads(next(r[2] for r in rows if r[0] == 'question'))['phase'], 'commentary')
            self.assertEqual(c.execute("SELECT count(*) FROM thread_turns WHERE status='interrupted'").fetchone()[0], 1)
            c.close()
            repair.install(bundle)
            with self.assertRaises(ValueError):
                repair.install(bundle)
            c = sqlite3.connect(home / 'state_5.sqlite')
            self.assertEqual(c.execute('SELECT title FROM threads WHERE id=?', (source,)).fetchone()[0], 'original')
            self.assertEqual(c.execute('SELECT count(*) FROM threads').fetchone()[0], 2)
            c.close()
            self.assertEqual(before, {p: repair.digest(p) for p in before})
            # Simulate deleting ONLY the fixture source, then read the installed copy.
            for file in before:
                file.unlink()
            c = sqlite3.connect(home / 'state_5.sqlite')
            c.execute('DELETE FROM threads WHERE id=?', (source,))
            c.commit()
            path = Path(c.execute('SELECT rollout_path FROM threads WHERE id=?', (m['new_id'],)).fetchone()[0])
            c.close()
            self.assertTrue(path.is_file())
            c = sqlite3.connect(home / 'thread_history_1.sqlite')
            c.execute('DELETE FROM thread_items WHERE thread_id=?', (source,))
            c.commit()
            self.assertEqual(c.execute('SELECT count(*) FROM thread_items WHERE thread_id=?', (m['new_id'],)).fetchone()[0], 5)
            c.close()
            repair.verify(bundle)
            with (bundle / 'rollout.jsonl').open('ab') as f:
                f.write(b'{}\n')
            with self.assertRaises(ValueError):
                repair.verify(bundle)

    def test_compressed_history_and_cutoff(self):
        try:
            import zstandard
        except ImportError:
            self.skipTest('Optional zstandard is not installed')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'history.jsonl.zst'
            lines = [(json.dumps(j, ensure_ascii=False) + '\n').encode('utf8') for j in
                     [{'type': 'session_meta', 'payload': {'id': '独立'}},
                      {'ordinal': 0, 'type': 'event_msg', 'payload': {'type': '中文'}}]]
            p.write_bytes(zstandard.ZstdCompressor().compress(b''.join(lines)))
            self.assertEqual(len(list(repair.records(p))), 2)
            self.assertEqual(len(list(repair.records(p, len(lines[0])))), 1)
            with self.assertRaises(ValueError):
                list(repair.records(p, len(lines[0]) - 1))


if __name__ == '__main__':
    unittest.main()
