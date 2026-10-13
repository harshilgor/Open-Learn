"""Restricted-shell operator tools for auditing unified usage.

Run only from an authenticated deployment shell. Mutating commands require a
named operator, reason, and stable idempotency key. No command is an HTTP API.
"""
import argparse
import json

from ..database import database_url
from .admin_ops import UsageAdmin
from .policy import Policy
from .transport import storage
from .ledger import Ledger


def _operator_arguments(command):
    command.add_argument('--actor', required=True, help='Named operator identity from the restricted deployment shell.')
    command.add_argument('--reason', required=True, help='Concise audit reason for the action.')
    command.add_argument('--idempotency-key', required=True, help='Stable 8–160 character key for safe retries.')


def _print(value):
    print(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    inspect = commands.add_parser('inspect', help='Inspect an exact existing owner without creating an account.')
    inspect.add_argument('owner')
    reconcile = commands.add_parser('reconcile', help='Conservatively settle expired dispatched holds and release undispatched holds.')
    _operator_arguments(reconcile)
    alerts = commands.add_parser('alerts', help='List recent unacknowledged provider-liability alerts.')
    alerts.add_argument('--limit', type=int, default=100)
    operations = commands.add_parser('operations', help='Read redacted queue, lease, delivery, and cleanup metrics.')
    operations.add_argument('--stale-queue-seconds', type=int, default=300)
    operations.add_argument('--stale-dispatch-seconds', type=int, default=90)
    ack = commands.add_parser('ack-alert', help='Acknowledge one alert with a durable operator audit record.')
    ack.add_argument('alert_id')
    _operator_arguments(ack)
    disable = commands.add_parser('disable-capability', help='Stop new metered admissions for a capability.')
    disable.add_argument('capability')
    _operator_arguments(disable)
    enable = commands.add_parser('enable-capability', help='Re-enable a previously disabled capability.')
    enable.add_argument('capability')
    _operator_arguments(enable)
    refund = commands.add_parser('refund', help='Return a bounded amount of learner credits for one settled reservation.')
    refund.add_argument('owner')
    refund.add_argument('reservation_id')
    refund.add_argument('microcredits', type=int)
    _operator_arguments(refund)
    reverse = commands.add_parser('reverse-refund', help='Reverse one prior refund if its original period has room.')
    reverse.add_argument('owner')
    reverse.add_argument('adjustment_id')
    _operator_arguments(reverse)
    unblock = commands.add_parser('unblock', help='Unblock an account after all provider outcomes are resolved.')
    unblock.add_argument('owner')
    _operator_arguments(unblock)

    args = parser.parse_args(argv)
    store = storage(database_url())
    ledger = Ledger(store, Policy.load())
    admin = UsageAdmin(store, ledger)
    if args.command == 'inspect':
        _print(admin.inspect(args.owner))
    elif args.command == 'reconcile':
        _print(admin.reconcile(actor=args.actor, reason=args.reason, idempotency_key=args.idempotency_key))
    elif args.command == 'alerts':
        _print(admin.open_alerts(args.limit))
    elif args.command == 'operations':
        _print(admin.operations_snapshot(stale_queue_seconds=args.stale_queue_seconds,
                                         stale_dispatch_seconds=args.stale_dispatch_seconds))
    elif args.command == 'ack-alert':
        _print(admin.acknowledge_alert(args.alert_id, actor=args.actor, reason=args.reason,
                                       idempotency_key=args.idempotency_key))
    elif args.command == 'disable-capability':
        _print(admin.set_capability(args.capability, True, actor=args.actor, reason=args.reason,
                                    idempotency_key=args.idempotency_key))
    elif args.command == 'enable-capability':
        _print(admin.set_capability(args.capability, False, actor=args.actor, reason=args.reason,
                                    idempotency_key=args.idempotency_key))
    elif args.command == 'refund':
        _print(admin.refund(args.owner, args.reservation_id, args.microcredits, actor=args.actor,
                            reason=args.reason, idempotency_key=args.idempotency_key))
    elif args.command == 'reverse-refund':
        _print(admin.reverse_refund(args.owner, args.adjustment_id, actor=args.actor,
                                    reason=args.reason, idempotency_key=args.idempotency_key))
    elif args.command == 'unblock':
        _print(admin.unblock(args.owner, actor=args.actor, reason=args.reason,
                             idempotency_key=args.idempotency_key))


if __name__ == '__main__':
    main()
