let settingsData, firstTime = false;
function hideToken() {
  $('cfg-token').type = 'password';
  $('token-reveal').setAttribute('aria-pressed', 'false');
  $('token-reveal').setAttribute('aria-label', 'Show Slack token');
  $('token-reveal').title = 'Show token';
  $('token-reveal').querySelector('.eye-slash').setAttribute('hidden', '');
}
function connectionState(id, state, message) {
  const element = $(id);
  element.dataset.state = state;
  element.textContent = `${{idle:'○', checking:'◌', success:'✓', error:'!'}[state]} ${message}`;
}
function resetChecks() {
  connectionState('slack-check', 'idle', 'Slack · not checked with these details');
  connectionState('provider-check', 'idle', 'AI provider · not checked with these details');
  $('connection-actions').hidden = true;
  $('settings-result').hidden = true;
}
function fieldError(input, message) {
  input.setAttribute('aria-invalid', 'true');
  const error = node('p', message, 'field-error'); error.id = `${input.id}-error`;
  input.setAttribute('aria-errormessage', error.id);
  (input.closest('.secret-input') || input).after(error);
  const details = input.closest('details'); if (details) details.open = true;
  const card = input.closest('.setup-card'); if (card) card.classList.add('has-error');
}
function clearFieldErrors() {
  for (const input of $('settings-form').querySelectorAll('[aria-invalid]')) {
    input.removeAttribute('aria-invalid'); input.removeAttribute('aria-errormessage');
  }
  for (const error of $('settings-form').querySelectorAll('.field-error')) error.remove();
  for (const card of $('settings-form').querySelectorAll('.has-error')) card.classList.remove('has-error');
}
function setupError(message) {
  $('settings-error').textContent = `Needs attention: ${message}`;
  $('settings-error').hidden = false;
  $('settings-error').focus();
}
function freezeForm() {
  const controls = [...$('settings-form').querySelectorAll('input, select, textarea, button')].map(input => [input, input.disabled]);
  for (const [input] of controls) input.disabled = true;
  return () => { for (const [input, disabled] of controls) input.disabled = disabled; };
}
function validateFields() {
  clearFieldErrors();
  let valid = true;
  for (const input of $('settings-form').querySelectorAll('input, select, textarea')) {
    if (!input.disabled && !input.checkValidity()) { fieldError(input, input.validationMessage); valid = false; }
  }
  const token = $('cfg-token').value.trim();
  if (token && !token.startsWith('xoxp-') && !/^env:[A-Za-z_][A-Za-z0-9_]*$/.test(token)) {
    fieldError($('cfg-token'), 'Use a Slack user token beginning xoxp- or env:VARIABLE_NAME.'); valid = false;
  }
  if (!valid) setupError('Check the highlighted fields. Nothing was saved.');
  return valid;
}

async function checkSetupConnections() {
  const unfreeze = freezeForm();
  connectionState('slack-check', 'checking', 'Checking Slack…');
  connectionState('provider-check', 'checking', 'Checking AI provider…');
  try {
    const {readiness: result} = await api('/api/status?check=true');
    $('readiness').textContent = `Slack: ${result.slack.message}\n${result.provider_name === 'ollama' ? 'Ollama' : 'Claude Code'}: ${result.provider.message}`;
    connectionState('slack-check', result.slack.ready ? 'success' : 'error', `Slack · ${result.slack.message}`);
    connectionState('provider-check', result.provider.ready ? 'success' : 'error', `${result.provider_name === 'ollama' ? 'Ollama' : 'Claude Code'} · ${result.provider.message}`);
    if (!result.ready) setupError('Settings saved, but a connection failed. See the Slack and AI indicators above. Fix the details and save again, recheck saved connections, or open the dashboard anyway.');
    else $('settings-error').hidden = true;
    return result.ready;
  } catch {
    connectionState('slack-check', 'error', 'Slack · check unavailable');
    connectionState('provider-check', 'error', 'AI provider · check unavailable');
    setupError('Settings saved, but connection checks could not finish. Check that Rundown is still running and try again.');
    return false;
  } finally {
    unfreeze();
    $('connection-actions').hidden = false;
  }
}
const conversations = [
  ['joined_public', 'Public channels I’ve joined'],
  ['private_channels', 'Private channels'],
  ['direct_messages', 'Direct messages'],
  ['group_messages', 'Group direct messages'],
  ['unjoined_public', 'Other visible public channels'],
];
const advanced = [
  ['storage', 'database', 'History database path', 'text'],
  ['slack', 'initial_lookback_hours', 'First run lookback (hours)', 'number', 1, 87600],
  ['slack', 'thread_tracking_days', 'Track active threads (days)', 'number', 1, 3650],
  ['ai', 'top_items', 'Priority messages per channel', 'number', 1, 50],
  ['ai', 'chunk_characters', 'AI input size (characters)', 'number', 2000, 200000],
  ['ai', 'timeout_seconds', 'AI timeout (seconds)', 'number', 1, 1800],
  ['ai', 'retries', 'AI retry attempts', 'number', 0, 3],
  ['slack', 'timeout_seconds', 'Slack timeout (seconds)', 'number', 1, 300],
  ['slack', 'retries', 'Slack retry attempts', 'number', 0, 8],
  ['slack', 'max_retry_after_seconds', 'Maximum rate-limit wait (seconds)', 'number', 1, 600],
];

for (const [key, label] of conversations) {
  const wrapper = node('label', undefined, 'checkbox-option');
  const input = node('input'); input.type = 'checkbox'; input.id = `cfg-${key}`;
  wrapper.append(input, document.createTextNode(label));
  $('conversation-options').append(wrapper);
}
for (const [section, key, title, type, min, max] of advanced) {
  const field = node('div'), label = node('label', title, 'field-label'), input = node('input', undefined, 'wide-input');
  input.id = `cfg-${section}-${key}`; input.type = type; input.required = true;
  label.htmlFor = input.id;
  if (type === 'number') { input.min = min; input.max = max; input.step = 1; }
  field.append(label, input); $('advanced-fields').append(field);
}

function providerFields() {
  const ollama = $('cfg-provider').value === 'ollama';
  $('ollama-fields').hidden = !ollama; $('claude-fields').hidden = ollama;
  for (const id of ['cfg-ollama-url', 'cfg-ollama-model']) { $(id).disabled = !ollama; $(id).required = ollama; }
  for (const id of ['cfg-claude-path', 'cfg-claude-model']) { $(id).disabled = ollama; $(id).required = !ollama; }
  $('provider-help').textContent = ollama
    ? 'Start Ollama and enter the name of a model you have downloaded. Your Slack content stays on your computer.'
    : 'Use an installed Claude Code CLI signed in with claude auth login. Selected Slack content is sent through your Claude account. No separate API key is needed.';
}

function populateSettings(data) {
  hideToken(); clearFieldErrors(); resetChecks();
  settingsData = data.config; firstTime = data.setup_required;
  const cfg = settingsData;
  $('cfg-token').value = '';
  $('cfg-token').required = !data.token_configured;
  $('cfg-token').placeholder = data.token_configured ? 'Token saved · leave blank to keep it' : 'xoxp-…';
  $('token-help').textContent = data.token_configured
    ? 'A token is already configured. Leave this field blank to keep it, or enter a replacement. Saved tokens are never displayed here.'
    : 'Your token is saved only in your local config file. You can also enter env:SLACK_USER_TOKEN.';
  for (const [key] of conversations) $(`cfg-${key}`).checked = cfg.slack[key];
  $('cfg-provider').value = cfg.ai.provider;
  $('cfg-ollama-url').value = cfg.ollama.base_url; $('cfg-ollama-model').value = cfg.ollama.model;
  $('cfg-claude-path').value = cfg.claude_code.executable; $('cfg-claude-model').value = cfg.claude_code.model;
  $('cfg-summaries').value = cfg.storage.summaries_dir; $('cfg-timezone').value = cfg.storage.timezone;
  $('cfg-keywords').value = Object.entries(cfg.keywords).map(([keyword, weight]) => `${keyword} = ${weight}`).join('\n');
  for (const [section, key] of advanced) $(`cfg-${section}-${key}`).value = cfg[section][key];
  $('setup-title').textContent = firstTime ? 'Setup' : 'Settings';
  $('settings-save').textContent = 'Save';
  $('settings-cancel').hidden = firstTime;
  $('settings-save').disabled = data.busy;
  $('settings-error').hidden = !data.busy;
  $('settings-error').textContent = data.busy ? 'A digest is running. Return to your rundown and open settings once it has finished.' : '';
  providerFields();
}

function showSettings() {
  clearTimeout(timer);
  $('loading-screen').hidden = true; $('dashboard').hidden = true;
  $('settings-screen').hidden = false; $('settings-open').hidden = true;
  $('setup-title').focus();
}

async function showDashboard(check = false) {
  hideToken(); $('cfg-token').value = '';
  $('loading-screen').hidden = true; $('settings-screen').hidden = true;
  $('dashboard').hidden = false; $('settings-open').hidden = false;
  await refresh();
  if (check) await checkConnections();
}

function readSettings() {
  const data = structuredClone(settingsData);
  data.slack.token = $('cfg-token').value.trim();
  for (const [key] of conversations) data.slack[key] = $(`cfg-${key}`).checked;
  data.ai.provider = $('cfg-provider').value;
  data.ollama.base_url = $('cfg-ollama-url').value.trim(); data.ollama.model = $('cfg-ollama-model').value.trim();
  data.claude_code.executable = $('cfg-claude-path').value.trim(); data.claude_code.model = $('cfg-claude-model').value.trim();
  data.storage.summaries_dir = $('cfg-summaries').value.trim(); data.storage.timezone = $('cfg-timezone').value.trim();
  data.keywords = Object.create(null);
  for (const [index, line] of $('cfg-keywords').value.split('\n').entries()) {
    if (!line.trim()) continue;
    const match = line.match(/^(.+?)\s*=\s*(\d+)\s*$/);
    if (!match || Number(match[2]) > 100) {
      const message = `Keyword line ${index + 1}: use keyword = weight, with a whole-number weight from 0 to 100.`;
      fieldError($('cfg-keywords'), message); throw new Error(message);
    }
    const keyword = match[1].trim();
    if (!keyword) throw new Error(`Keyword line ${index + 1} needs a keyword or phrase.`);
    data.keywords[keyword] = Number(match[2]);
  }
  for (const [section, key, , type] of advanced) data[section][key] = type === 'number' ? Number($(`cfg-${section}-${key}`).value) : $(`cfg-${section}-${key}`).value.trim();
  return data;
}

$('cfg-provider').onchange = providerFields;
$('token-reveal').onclick = () => {
  if ($('cfg-token').type === 'text') return hideToken();
  $('cfg-token').type = 'text';
  $('token-reveal').setAttribute('aria-pressed', 'true');
  $('token-reveal').setAttribute('aria-label', 'Hide Slack token');
  $('token-reveal').title = 'Hide token';
  $('token-reveal').querySelector('.eye-slash').removeAttribute('hidden');
};
document.addEventListener('visibilitychange', () => { if (document.hidden) hideToken(); });
$('settings-form').addEventListener('input', () => {
  clearFieldErrors(); resetChecks(); $('settings-error').hidden = true;
});
$('settings-recheck').onclick = checkSetupConnections;
$('settings-continue').onclick = () => showDashboard().catch(error => setupError(error.message));
$('settings-open').onclick = async () => {
  try { populateSettings(await api('/api/config')); showSettings(); }
  catch (error) { notice(error.message, true); }
};
$('settings-cancel').onclick = () => showDashboard().catch(error => notice(error.message, true));
$('settings-form').onsubmit = async (event) => {
  event.preventDefault();
  hideToken();
  $('settings-error').hidden = true;
  if (!validateFields()) return;
  let data;
  try { data = readSettings(); }
  catch (error) { setupError(error.message); return; }
  const unfreeze = freezeForm();
  $('settings-form').setAttribute('aria-busy', 'true');
  try {
    const saved = await api('/api/config', {method:'POST', headers:{'Content-Type':'application/json','X-Rundown-Request':'1'}, body:JSON.stringify(data)});
    $('cfg-token').value = ''; // Do not retain the submitted credential in the DOM.
    hideToken();
    settingsData = saved.config; firstTime = saved.setup_required;
    $('cfg-token').required = !saved.token_configured;
    $('cfg-token').placeholder = 'Token saved · leave blank to keep it';
    $('token-help').textContent = 'Your token is saved. Leave blank to keep it. The eye only reveals a new token you type, never the saved token.';
    $('settings-save').textContent = 'Save';
    $('settings-cancel').hidden = false;
    $('settings-result').textContent = '✓ Settings saved on this computer. Checking your connections…';
    $('settings-result').hidden = false;
    selectedDate = undefined; selectedRun = undefined;
    if (await checkSetupConnections()) {
      await showDashboard();
      notice('Settings saved. Slack and your AI provider are connected.');
    }
    $('settings-result').textContent = '✓ Settings saved. Changes are active.';
  } catch (error) {
    if (!$('settings-screen').hidden) {
      for (const [prefix, id] of [['storage.timezone', 'cfg-timezone'], ['ollama.base_url', 'cfg-ollama-url'], ['keywords', 'cfg-keywords']]) {
        if (error.message.includes(prefix)) fieldError($(id), 'Check this setting. Details below.');
      }
      setupError(error.message);
    }
    else notice(error.message, true);
  } finally {
    unfreeze(); $('settings-form').removeAttribute('aria-busy');
  }
};

async function initializeApp() {
  try {
    const data = await api('/api/config');
    if (data.setup_required) { populateSettings(data); showSettings(); }
    else await showDashboard(true);
  } catch (error) {
    $('loading-message').textContent = `Could not load Rundown: ${error.message}. Reload the page to try again.`;
    if (!$('dashboard').hidden) notice(error.message, true);
  } finally {
    $('dev-toggle').disabled = false;
  }
}
initializeApp();
