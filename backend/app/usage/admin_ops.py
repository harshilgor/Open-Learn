"""Audited restricted-shell operations for the unified usage ledger.

This module is intentionally not exposed as an HTTP API. Commands must run in
an authenticated deployment shell and supply a named actor, reason, and stable
idempotency key for every mutation.
"""
import json
import re
import uuid

from sqlalchemy import text

from .ledger import Ledger, UsageError


CAPABILITIES = frozenset({
    'all', 'model', 'stt', 'tts', 'voice', 'browser', 'search',
    'classification', 'embeddings', 'tool',
})
_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$')


def _exact_text(value, label, limit):
    if (not isinstance(value, str) or not value or len(value) > limit or
            value != value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise ValueError(f'{label} must be an exact non-empty value of at most {limit} characters.')
    return value


def _actor(value):
    return _exact_text(value, 'Actor', 160)


def _reason(value):
    return _exact_text(value, 'Reason', 500)


def _owner(value):
    return _exact_text(value, 'Owner id', 160)


def _entity_id(value, label, limit=200):
    return _exact_text(value, label, limit)


def _idempotency(value):
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise ValueError('Idempotency key must be 8–160 ASCII letters, digits, dots, underscores, colons, or hyphens.')
    return value


class UsageAdmin:
    def __init__(self, store, ledger=None):
        self.store = store
        self.ledger = ledger or Ledger(store)

    def inspect(self, owner):
        owner = _owner(owner)
        with self.store.engine.connect() as conn:
            account = conn.execute(text('SELECT * FROM usage_accounts WHERE owner_id=:owner'),
                                   {'owner': owner}).mappings().first()
            if not account:
                raise ValueError('Unknown owner id; inspection never creates accounts.')
            periods = conn.execute(text('''SELECT id,starts_at,expires_at,grant_micro,used_micro,held_micro,policy_version
                FROM usage_periods WHERE owner_id=:owner ORDER BY starts_at DESC LIMIT 5'''),
                                   {'owner': owner}).mappings().all()
            reservations = conn.execute(text('''SELECT id,operation_key,period_id,component,root_id,state,held_micro,
                liability_nano,created_at,deadline,dispatched_at,settled_at,provider,model,receipt_id
                FROM usage_reservations WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 25'''),
                                        {'owner': owner}).mappings().all()
            events = conn.execute(text('''SELECT id,reservation_id,period_id,root_id,component,microcredits,cost_nano,
                source,created_at,provider,model,receipt_id,adjustment_of
                FROM usage_events WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 25'''),
                                  {'owner': owner}).mappings().all()
            adjustments = conn.execute(text('''SELECT id,actor,reason,kind,microcredits,created_at,reservation_id
                FROM usage_adjustments WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 25'''),
                                       {'owner': owner}).mappings().all()
            task_caps = conn.execute(text('''SELECT root_id,maximum_micro,policy_version,created_at
                FROM usage_task_caps WHERE owner_id=:owner ORDER BY created_at DESC LIMIT 25'''),
                                     {'owner': owner}).mappings().all()
        return {
            'account': {key: account[key] for key in ('owner_id', 'revision', 'blocked', 'status', 'plan_id', 'current_period_id')},
            'allowance': self.ledger.allowance(owner),
            'periods': [dict(row) for row in periods],
            'reservations': [dict(row) for row in reservations],
            'events': [dict(row) for row in events],
            'adjustments': [dict(row) for row in adjustments],
            'taskCaps': [dict(row) for row in task_caps],
        }

    def open_alerts(self, limit=100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError('Alert limit must be between 1 and 500.')
        with self.store.engine.connect() as conn:
            rows = conn.execute(text('''SELECT id,owner_id,reservation_id,kind,created_at,payload
                FROM usage_alerts WHERE acknowledged_at IS NULL ORDER BY created_at LIMIT :limit'''),
                                {'limit': limit}).mappings().all()
        return [dict(row) for row in rows]

    def operations_snapshot(self, *, stale_queue_seconds=300, stale_dispatch_seconds=90):
        """Return a privacy-safe aggregate view of durable work and cleanup.

        This deliberately exposes counts and ages only: no owner identifiers,
        task text, provider URLs, or operation payloads.  It is read-only and
        uses the existing job, outbox, usage, and cleanup ledgers.
        """
        for value, label in ((stale_queue_seconds, 'Queue age'), (stale_dispatch_seconds, 'Dispatch age')):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
                raise ValueError(f'{label} threshold must be between 1 and 86400 seconds.')

        with self.store.engine.connect() as conn:
            now = self.ledger.now(conn)
            jobs = conn.execute(text('''SELECT queue,status,COUNT(*) AS count FROM learning_jobs
                GROUP BY queue,status ORDER BY queue,status''')).mappings().all()
            job_counts = {(row['queue'], row['status']): int(row['count']) for row in jobs}
            stale_queue = conn.execute(text('''SELECT COUNT(*),MIN(created_at) FROM learning_jobs
                WHERE status IN ('queued','retry_wait') AND next_retry_at<=:now
                  AND created_at<=:cutoff'''), {'now': now, 'cutoff': now-stale_queue_seconds}).one()
            expired_leases = conn.execute(text('''SELECT COUNT(*),MIN(expires) FROM learning_jobs
                WHERE status='running' AND expires IS NOT NULL AND expires<=:now'''), {'now': now}).one()
            exhausted = conn.execute(text('''SELECT COUNT(*),MIN(created_at) FROM learning_jobs
                WHERE status='failed' AND attempt_count>=max_attempts''')).one()

            def count_age(table, where='1=1', timestamp='created_at', params=None):
                from sqlalchemy import inspect
                if not inspect(conn).has_table(table):
                    return (0, None)
                aggregate = f'MIN({timestamp})' if timestamp else 'NULL'
                return conn.execute(text(f'SELECT COUNT(*),{aggregate} FROM {table} WHERE {where}'), params or {}).one()

            stale_outbox = count_age('execution_outbox',
                'delivered_at IS NULL AND failed_at IS NULL AND created_at<=:cutoff',
                params={'cutoff': now-stale_queue_seconds})
            outbox_failed = count_age('execution_outbox', 'failed_at IS NOT NULL', timestamp='failed_at')
            unknown_writes = count_age('agent_action_operations', "status='outcome_unknown'")
            stale_dispatch = count_age('agent_action_operations',
                "status='dispatching' AND updated_at<=:cutoff", timestamp='updated_at',
                params={'cutoff': now-stale_dispatch_seconds})
            sandbox_cleanup = count_age('agent_sandbox_cleanup')
            assistant_object_cleanup = count_age('identity_object_cleanup', "kind='assistant'", timestamp=None)
            browser_cleanup = count_age('browser_provider_cleanup')
            artifact_cleanup = count_age('agent_artifacts', "status='cleanup_pending'")
            failed_reminders = count_age('reminders', "status='failed'", timestamp='due_at')
            failed_notification_delivery = count_age('notification_deliveries', "status='failed'")
            unresolved_usage = count_age('usage_reservations',
                "state='dispatched' AND deadline<:now", timestamp='deadline', params={'now': now})
            expired_sandbox_leases = count_age('agent_sandbox_leases',
                "status NOT IN ('released','deleted') AND expires_at<=:now", timestamp='created_at', params={'now': now})
            active_sandbox_leases = count_age('agent_sandbox_leases',
                "status IN ('creating','active','executing','collected')", timestamp='created_at')

        def metric(row):
            count = int(row[0] or 0)
            oldest = float(row[1]) if len(row) > 1 and row[1] is not None else None
            return {'count': count, 'oldestAgeSeconds': max(0, int(now-oldest)) if oldest is not None else None}

        metrics = {
            'jobsByQueueAndStatus': [dict(row) for row in jobs],
            'staleQueuedJobs': metric(stale_queue),
            'expiredJobLeases': metric(expired_leases),
            'exhaustedJobs': metric(exhausted),
            'staleOutboxDeliveries': metric(stale_outbox),
            'failedOutboxDeliveries': metric(outbox_failed),
            'unknownExternalWrites': metric(unknown_writes),
            'staleExternalDispatches': metric(stale_dispatch),
            'sandboxCleanupObligations': metric(sandbox_cleanup),
            'assistantObjectCleanupObligations': metric(assistant_object_cleanup),
            'browserCleanupObligations': metric(browser_cleanup),
            'artifactCleanupPending': metric(artifact_cleanup),
            'failedReminderDeliveries': metric(failed_reminders),
            'failedNotificationDeliveries': metric(failed_notification_delivery),
            'expiredUsageReservations': metric(unresolved_usage),
            'expiredSandboxLeases': metric(expired_sandbox_leases),
            'activeSandboxLeases': metric(active_sandbox_leases),
        }
        alert_map = {
            'stale_jobs': 'staleQueuedJobs',
            'expired_leases': 'expiredJobLeases',
            'exhausted_jobs': 'exhaustedJobs',
            'outbox_stale': 'staleOutboxDeliveries',
            'outbox_failed': 'failedOutboxDeliveries',
            'write_unknown': 'unknownExternalWrites',
            'write_dispatch_stale': 'staleExternalDispatches',
            'sandbox_cleanup': 'sandboxCleanupObligations',
            'object_cleanup': 'assistantObjectCleanupObligations',
            'browser_cleanup': 'browserCleanupObligations',
            'artifact_cleanup': 'artifactCleanupPending',
            'reminder_failed': 'failedReminderDeliveries',
            'notification_failed': 'failedNotificationDeliveries',
            'usage_reconciliation': 'expiredUsageReservations',
            'sandbox_lease_expiry': 'expiredSandboxLeases',
        }
        alerts = [{'kind': kind, **metrics[key]} for kind, key in alert_map.items() if metrics[key]['count']]
        return {'sampledAt': now, 'thresholds': {'staleQueueSeconds': stale_queue_seconds,
                'staleDispatchSeconds': stale_dispatch_seconds}, 'metrics': metrics, 'alerts': alerts}

    def emit_operations_alerts(self, *, stale_queue_seconds=300, stale_dispatch_seconds=90, snapshot=None):
        """Persist redacted platform-health alerts for the authenticated worker loop.

        Alert identities coalesce one metric per UTC hour. Payloads contain only
        aggregate counts and age, and use the existing durable/acknowledgeable
        usage alert store. This is intentionally not an HTTP control surface.
        """
        snapshot = snapshot or self.operations_snapshot(stale_queue_seconds=stale_queue_seconds,
                                                        stale_dispatch_seconds=stale_dispatch_seconds)
        hour = int(float(snapshot['sampledAt']) // 3600)
        inserted = 0
        with self.ledger.transaction() as conn:
            for alert in snapshot['alerts']:
                kind = str(alert['kind'])
                identifier = f'agent-ops:{kind}:{hour}'
                result = conn.execute(text('''INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload)
                    VALUES(:id,NULL,NULL,:kind,:now,:payload) ON CONFLICT(id) DO NOTHING'''), {
                    'id': identifier, 'kind': 'agent_' + kind, 'now': snapshot['sampledAt'],
                    'payload': json.dumps({'metric': kind, 'count': int(alert['count']),
                        'oldestAgeSeconds': alert.get('oldestAgeSeconds')}, separators=(',', ':')),
                })
                inserted += max(0, result.rowcount)
        return {'observed': len(snapshot['alerts']), 'created': inserted}


    def unblock(self, owner, *, actor, reason, idempotency_key):
        owner = _owner(owner)
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        target = 'account:' + owner
        with self.store.engine.connect() as conn:
            prior = self._replay(conn, key, actor, 'unblock', target, reason)
            exists = conn.execute(text('SELECT 1 FROM usage_accounts WHERE owner_id=:owner'),
                                  {'owner': owner}).first()
        if prior is not None:
            return prior
        if not exists:
            raise ValueError('Unknown owner id; unblock never creates accounts.')
        changed = self.ledger.unblock(owner, actor, reason)
        result = {'ownerId': owner, 'changed': changed, 'replayed': False}
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, 'unblock', target, reason)
            if prior is not None:
                return prior
            now = self.ledger.now(conn)
            self._audit(conn, key, actor, 'unblock', target, reason, now, result)
        return result

    def _replay(self, conn, key, actor, action, target, reason):
        row = conn.execute(text('SELECT * FROM usage_admin_audit WHERE idempotency_key=:key'),
                           {'key': key}).mappings().first()
        if not row:
            return None
        if (row['actor'], row['action'], row['target'], row['reason']) != (actor, action, target, reason):
            raise UsageError('usage_admin_idempotency_conflict',
                             'This operator idempotency key belongs to a different action.', 409)
        result = json.loads(row['payload'])
        if isinstance(result, dict):
            result['replayed'] = True
        return result

    def _audit(self, conn, key, actor, action, target, reason, now, result):
        conn.execute(text('''INSERT INTO usage_admin_audit(id,idempotency_key,actor,action,target,reason,created_at,payload)
            VALUES(:id,:key,:actor,:action,:target,:reason,:now,:payload)'''), {
            'id': 'admin:' + uuid.uuid4().hex, 'key': key, 'actor': actor, 'action': action,
            'target': target, 'reason': reason, 'now': now,
            'payload': json.dumps(result, sort_keys=True, separators=(',', ':')),
        })

    def reconcile(self, *, actor, reason, idempotency_key):
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        action, target = 'reconcile', 'expired-reservations'
        with self.store.engine.connect() as conn:
            prior = self._replay(conn, key, actor, action, target, reason)
        if prior is not None:
            return prior
        # Reconciliation is state-idempotent. The audit row is written after
        # settlements; if the process stops between them, retry safely observes
        # the already-settled reservations and records the completed command.
        count = self.ledger.reconcile()
        result = {'settledOrReleased': count, 'replayed': False}
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, action, target, reason)
            if prior is not None:
                return prior
            now = self.ledger.now(conn)
            self._audit(conn, key, actor, action, target, reason, now, result)
        return result

    def acknowledge_alert(self, alert_id, *, actor, reason, idempotency_key):
        alert_id = _entity_id(alert_id, 'Alert id', 160)
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        target = 'alert:' + alert_id
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, 'alert_ack', target, reason)
            if prior is not None:
                return prior
            alert = conn.execute(text('SELECT id FROM usage_alerts WHERE id=:id'), {'id': alert_id}).first()
            if not alert:
                raise ValueError('Unknown usage alert id.')
            now = self.ledger.now(conn)
            changed = conn.execute(text('''UPDATE usage_alerts SET acknowledged_at=:now
                WHERE id=:id AND acknowledged_at IS NULL'''), {'id': alert_id, 'now': now}).rowcount == 1
            result = {'alertId': alert_id, 'acknowledged': True, 'changed': changed, 'replayed': False}
            self._audit(conn, key, actor, 'alert_ack', target, reason, now, result)
            return result

    def set_capability(self, capability, disabled, *, actor, reason, idempotency_key):
        capability = _exact_text(capability, 'Capability', 40).lower()
        if capability not in CAPABILITIES:
            raise ValueError('Unsupported capability. Choose one of: ' + ', '.join(sorted(CAPABILITIES)) + '.')
        if not isinstance(disabled, bool):
            raise ValueError('Capability state must be enabled or disabled.')
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        action = 'capability_disable' if disabled else 'capability_enable'
        target = 'capability:' + capability
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, action, target, reason)
            if prior is not None:
                return prior
            now = self.ledger.now(conn)
            conn.execute(text('''INSERT INTO usage_capability_controls(capability,disabled,actor,reason,updated_at)
                VALUES(:capability,:disabled,:actor,:reason,:now)
                ON CONFLICT(capability) DO NOTHING'''), {
                'capability': capability, 'disabled': disabled, 'actor': actor, 'reason': reason, 'now': now,
            })
            current = self.ledger.lock(conn, 'usage_capability_controls', 'capability', capability)
            changed = current['disabled'] != disabled
            conn.execute(text('''UPDATE usage_capability_controls SET disabled=:disabled,actor=:actor,
                reason=:reason,updated_at=:now WHERE capability=:capability'''), {
                'capability': capability, 'disabled': disabled, 'actor': actor, 'reason': reason, 'now': now,
            })
            result = {'capability': capability, 'disabled': disabled, 'changed': changed, 'replayed': False}
            self._audit(conn, key, actor, action, target, reason, now, result)
            return result

    def refund(self, owner, reservation_id, microcredits, *, actor, reason, idempotency_key):
        owner = _owner(owner)
        reservation_id = _entity_id(reservation_id, 'Reservation id', 160)
        if isinstance(microcredits, bool) or not isinstance(microcredits, int) or microcredits <= 0:
            raise ValueError('Refund microcredits must be a positive integer.')
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        target = f'reservation:{reservation_id}'
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, 'refund', target, reason)
            if prior is not None:
                return prior
            self.ledger.lock(conn, 'usage_accounts', 'owner_id', owner)
            reservation = conn.execute(text('''SELECT * FROM usage_reservations
                WHERE id=:id AND owner_id=:owner'''), {'id': reservation_id, 'owner': owner}).mappings().first()
            if not reservation or reservation['state'] != 'settled':
                raise ValueError('Refund requires an exact owner match and a settled reservation.')
            original = conn.execute(text('''SELECT * FROM usage_events
                WHERE id=:id AND owner_id=:owner AND reservation_id=:id'''),
                                    {'id': reservation_id, 'owner': owner}).mappings().first()
            if not original or original['microcredits'] <= 0:
                raise ValueError('This reservation has no positive learner debit to refund.')
            adjustment_rows = conn.execute(text('''SELECT kind,microcredits FROM usage_adjustments
                WHERE owner_id=:owner AND reservation_id=:reservation AND kind IN ('refund','refund_reversal')'''),
                                           {'owner': owner, 'reservation': reservation_id}).all()
            refunded = sum(row.microcredits for row in adjustment_rows if row.kind == 'refund')
            refunded += sum(row.microcredits for row in adjustment_rows if row.kind == 'refund_reversal')
            if microcredits > original['microcredits'] - refunded:
                raise ValueError('Refund cannot exceed the operation’s remaining original debit.')
            now = self.ledger.now(conn)
            changed = conn.execute(text('''UPDATE usage_periods SET used_micro=used_micro-:amount
                WHERE id=:period AND owner_id=:owner AND used_micro>=:amount'''), {
                'amount': microcredits, 'period': original['period_id'], 'owner': owner,
            }).rowcount
            if changed != 1:
                raise UsageError('usage_adjustment_conflict', 'The original period no longer contains the requested debit.', 409)
            adjustment_id = 'adjustment:' + uuid.uuid4().hex
            conn.execute(text('''INSERT INTO usage_adjustments(id,owner_id,actor,reason,kind,microcredits,created_at,reservation_id)
                VALUES(:id,:owner,:actor,:reason,'refund',:amount,:now,:reservation)'''), {
                'id': adjustment_id, 'owner': owner, 'actor': actor, 'reason': reason,
                'amount': microcredits, 'now': now, 'reservation': reservation_id,
            })
            conn.execute(text('''INSERT INTO usage_events(id,owner_id,reservation_id,period_id,root_id,component,microcredits,
                cost_nano,source,created_at,payload,provider,model,currency,receipt_id,provider_rate_version,adjustment_of)
                VALUES(:id,:owner,:reservation,:period,:root,:component,:credits,0,'adjustment',:now,:payload,
                :provider,:model,'USD',NULL,:rate_version,:adjustment_of)'''), {
                'id': adjustment_id, 'owner': owner, 'reservation': reservation_id, 'period': original['period_id'],
                'root': original['root_id'], 'component': original['component'], 'credits': -microcredits,
                'now': now, 'payload': json.dumps({'kind': 'refund', 'adjustmentId': adjustment_id}, separators=(',', ':')),
                'provider': original['provider'], 'model': original['model'],
                'rate_version': original['provider_rate_version'], 'adjustment_of': reservation_id,
            })
            self.ledger.update(conn, owner, now, 'usage.operator_refunded')
            result = {'adjustmentId': adjustment_id, 'reservationId': reservation_id,
                      'microcredits': microcredits, 'replayed': False}
            self._audit(conn, key, actor, 'refund', target, reason, now, result)
            return result

    def reverse_refund(self, owner, adjustment_id, *, actor, reason, idempotency_key):
        owner = _owner(owner)
        adjustment_id = _entity_id(adjustment_id, 'Adjustment id', 160)
        actor, reason, key = _actor(actor), _reason(reason), _idempotency(idempotency_key)
        target = f'refund:{adjustment_id}'
        with self.ledger.transaction() as conn:
            prior = self._replay(conn, key, actor, 'refund_reversal', target, reason)
            if prior is not None:
                return prior
            self.ledger.lock(conn, 'usage_accounts', 'owner_id', owner)
            refund = conn.execute(text('''SELECT * FROM usage_adjustments
                WHERE id=:id AND owner_id=:owner AND kind='refund' AND microcredits>0'''),
                                  {'id': adjustment_id, 'owner': owner}).mappings().first()
            if not refund:
                raise ValueError('Unknown refund adjustment id for this owner.')
            prior_reversal = conn.execute(text('''SELECT 1 FROM usage_admin_audit
                WHERE action='refund_reversal' AND target=:target LIMIT 1'''), {'target': target}).first()
            if prior_reversal:
                raise ValueError('This refund has already been reversed.')
            original_event = conn.execute(text('''SELECT * FROM usage_events
                WHERE id=:id AND owner_id=:owner AND adjustment_of=:reservation'''),
                                         {'id': adjustment_id, 'owner': owner,
                                          'reservation': refund['reservation_id']}).mappings().first()
            if not original_event or original_event['microcredits'] != -refund['microcredits']:
                raise UsageError('usage_adjustment_conflict', 'The refund event is missing or inconsistent.', 409)
            now = self.ledger.now(conn)
            changed = conn.execute(text('''UPDATE usage_periods SET used_micro=used_micro+:amount
                WHERE id=:period AND owner_id=:owner AND used_micro+held_micro+:amount<=grant_micro'''), {
                'amount': refund['microcredits'], 'period': original_event['period_id'], 'owner': owner,
            }).rowcount
            if changed != 1:
                raise UsageError('usage_adjustment_conflict', 'The original window has insufficient unused allowance to reverse this refund.', 409)
            reversal_id = 'adjustment:' + uuid.uuid4().hex
            conn.execute(text('''INSERT INTO usage_adjustments(id,owner_id,actor,reason,kind,microcredits,created_at,reservation_id)
                VALUES(:id,:owner,:actor,:reason,'refund_reversal',:amount,:now,:reservation)'''), {
                'id': reversal_id, 'owner': owner, 'actor': actor, 'reason': reason,
                'amount': -refund['microcredits'], 'now': now, 'reservation': refund['reservation_id'],
            })
            conn.execute(text('''INSERT INTO usage_events(id,owner_id,reservation_id,period_id,root_id,component,microcredits,
                cost_nano,source,created_at,payload,provider,model,currency,receipt_id,provider_rate_version,adjustment_of)
                VALUES(:id,:owner,:reservation,:period,:root,:component,:credits,0,'adjustment',:now,:payload,
                :provider,:model,'USD',NULL,:rate_version,:adjustment_of)'''), {
                'id': reversal_id, 'owner': owner, 'reservation': refund['reservation_id'],
                'period': original_event['period_id'], 'root': original_event['root_id'],
                'component': original_event['component'], 'credits': refund['microcredits'],
                'now': now, 'payload': json.dumps({'kind': 'refund_reversal', 'adjustmentId': reversal_id,
                                                   'reverses': adjustment_id}, separators=(',', ':')),
                'provider': original_event['provider'], 'model': original_event['model'],
                'rate_version': original_event['provider_rate_version'], 'adjustment_of': adjustment_id,
            })
            self.ledger.update(conn, owner, now, 'usage.operator_refund_reversed')
            result = {'adjustmentId': reversal_id, 'reverses': adjustment_id,
                      'microcredits': refund['microcredits'], 'replayed': False}
            self._audit(conn, key, actor, 'refund_reversal', target, reason, now, result)
            return result
