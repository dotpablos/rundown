const test = require('node:test');
const assert = require('node:assert/strict');
const {createDemoArchive, demoResponse} = require('../rundown/static/demo.js');

test('preview contains dated history, multiple runs, priorities, and a partial run', () => {
  const archive = createDemoArchive('2026-01-01');
  const dates = demoResponse('/api/dates', {}, archive, 'America/Edmonton');
  assert.equal(dates[0].date, '2026-01-01');
  assert.equal(dates[0].count, 2);
  assert.equal(dates[1].date, '2025-12-31');
  assert.equal(archive.filter(run => run.status === 'partial').length, 1);
  assert.equal(archive[0].channels.length, 3);
  assert.deepEqual(archive[0].channels.map(c => c.digest.priority_items[0].score), [16, 9, 7]);
  assert.ok(archive.every(run => run.channels.every(c => c.digest.priority_items.every(p => p.slack_link === ''))));
});

test('preview API isolates fixture data and returns empty results for quiet dates', () => {
  const archive = createDemoArchive('2026-10-20');
  const run = demoResponse('/api/digests?date=2026-10-20', {}, archive, 'America/Edmonton')[0];
  run.channels[0].digest.overview = 'changed';
  assert.notEqual(archive[0].channels[0].digest.overview, 'changed');
  assert.deepEqual(demoResponse('/api/digests?date=2020-01-01', {}, archive, 'America/Edmonton'), []);
  const status = demoResponse('/api/status', {}, archive, 'America/Edmonton');
  assert.equal(status.provider_name, 'demo');
  assert.equal(status.busy, false);
});

test('preview blocks every write and unsupported endpoint', () => {
  const archive = createDemoArchive('2026-10-20');
  for (const path of ['/api/config', '/api/runs']) {
    assert.throws(() => demoResponse(path, {method:'POST'}, archive, 'UTC'), /read-only/);
  }
  assert.throws(() => demoResponse('/api/config', {}, archive, 'UTC'), /unavailable/);
});
