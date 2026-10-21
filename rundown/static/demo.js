// Synthetic preview data. Never read from or written to the server.
function createDemoArchive(todayKey) {
  const channels = [
    {channel_id:'demo-engineering', channel_name:'engineering', message_count:18, digest:{
      overview:'Release testing is complete. One deployment blocker remains.',
      key_updates:['The API migration passed staging checks.', 'The deployment checklist is ready.'],
      action_items:['Resolve the database timeout before the release.', 'Review the rollback steps.'],
      decisions:['Deploy after the blocker is resolved.'],
      priority_items:[{source_ts:'demo-1',slack_link:'',matched_keywords:['blocker','urgent'],ai_priority:3,score:16,explanation:'Database timeouts are blocking the release.'}],
    }},
    {channel_id:'demo-support', channel_name:'support', message_count:9, digest:{
      overview:'Two customer reports need follow-up. No service outage was reported.',
      key_updates:['A workaround for delayed exports is available.'],
      action_items:['Send the workaround to affected customers.'], decisions:[],
      priority_items:[{source_ts:'demo-2',slack_link:'',matched_keywords:['customer','help'],ai_priority:2,score:9,explanation:'Follow up on delayed customer exports.'}],
    }},
    {channel_id:'demo-product',channel_name:'product',message_count:12,digest:{
      overview:'The team agreed on a smaller scope for the next iteration.',
      key_updates:['Dashboard filters are included in the next iteration.'],
      action_items:['Review the updated acceptance criteria.'],
      decisions:['Defer notification scheduling to a later release.'],
      priority_items:[{source_ts:'demo-3',slack_link:'',matched_keywords:['decision','review'],ai_priority:1,score:7,explanation:'Review the revised scope before planning.'}],
    }},
  ];
  const runs = [];
  for (const [offset, hour] of [[0,15],[0,9],[1,10],[3,9],[6,11]]) {
    const date = new Date(`${todayKey}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() - offset);
    const key = date.toISOString().slice(0,10);
    const partial = offset === 3;
    runs.push({id:`demo-${key}-${hour}`,date:key,started_at:`${key}T${String(hour).padStart(2,'0')}:00:00Z`,
      status:partial ? 'partial' : 'completed',provider:'demo',model:'Sample data',total:3,processed:3,
      errors:partial ? [{channel:'support',error:'Sample error: channel unavailable. Retry on the next run.'}] : [],
      channels:structuredClone(partial ? [channels[0],channels[2]] : channels),
    });
  }
  return runs;
}

function demoResponse(path, options, archive, timezone) {
  if (options.method && options.method !== 'GET') throw new Error('Developer preview is read-only. Exit preview to run a digest or change settings.');
  const url = new URL(path, 'http://rundown.local');
  if (url.pathname === '/api/status') return {busy:false,latest:archive[0],provider_name:'demo',timezone,setup_required:false};
  if (url.pathname === '/api/dates') {
    const counts = new Map();
    for (const run of archive) counts.set(run.date,(counts.get(run.date)||0)+1);
    return [...counts].map(([date,count]) => ({date,count}));
  }
  if (url.pathname === '/api/digests') return structuredClone(archive.filter(run => run.date === url.searchParams.get('date')));
  throw new Error('This action is unavailable in developer preview.');
}

if (typeof module !== 'undefined') module.exports = {createDemoArchive, demoResponse};
