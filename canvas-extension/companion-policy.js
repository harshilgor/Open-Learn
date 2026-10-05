export function allowedUrl(value, config) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return false;
    if (/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|169\.254\.|\[|0\.)/i.test(url.hostname) || /\.(local|internal|localhost)$/i.test(url.hostname)) return false;
    return [config.origin, ...(config.approvedOrigins || [])].includes(url.origin);
  } catch { return false; }
}

export function validateCommand(command, config) {
  if (command.deadline * 1000 <= Date.now() || command.connectionRevision < 1 || !command.generation || !command.taskId) throw Error('outcome_unknown');
  if (command.origin !== config.origin) throw Error('origin_not_approved');
  if (command.action.url && !allowedUrl(command.action.url, config)) throw Error('origin_not_approved');
  if (command.action.cursor && !allowedUrl(command.action.cursor, config)) throw Error('origin_not_approved');
  return command;
}

export function safeControl(control, action, config) {
  if (!control || /\b(submit|purchase|pay|delete|remove|send|enroll|drop|withdraw|start (quiz|exam|attempt)|begin (quiz|exam|attempt))\b|password|credit.?card|verification code/i.test(control.name)) throw Error('action_blocked');
  if (control.href && !allowedUrl(control.href, config)) throw Error('origin_not_approved');
  if (['fill','press_key'].includes(action.tool) && !control.writable) throw Error('action_blocked');
  if (action.tool === 'press_key' && !['Enter','Escape','ArrowDown','ArrowUp','Tab'].includes(action.value)) throw Error('action_blocked');
  return control;
}
