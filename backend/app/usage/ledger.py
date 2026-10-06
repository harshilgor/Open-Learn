"""Durable account reservations. External work happens after transaction commit."""
import hashlib
import json
import uuid
import base64
import math
import time
from datetime import datetime, timezone
from sqlalchemy import text
from fastapi import HTTPException
from .policy import Policy
from .pricing import price


class UsageError(HTTPException):
    def __init__(self, code, message, status=429, reset=None):
        headers=None
        if status==429 and isinstance(reset,(int,float)) and reset>time.time():
            headers={'Retry-After':str(max(1,math.ceil(reset-time.time())))}
        super().__init__(status, {'code':code,'message':message,'resetsAt':reset,
                                  'retryable':status==429 or status>=500},headers=headers)


def _usage_capability(component, provider, model, quantities):
    if component != 'tool':
        return component
    if 'embedding_requests' in quantities:
        return 'embeddings'
    if provider == 'exa':
        return 'search'
    if provider == 'openrouter' and isinstance(model, str) and model.startswith('typesafe/jev-'):
        return 'classification'
    return 'tool'


class Ledger:
    RECONCILIATION_ALERT_GRACE_SECONDS = 60
    OUTBOX_ALERT_ROWS = 100_000
    USER_ADMISSIONS_PER_MINUTE = 5

    def __init__(self, store, policy=None, clock=None):
        self.store, self.policy, self.clock = store, policy or Policy.load(), clock

    def now(self, conn):
        if self.clock: return self.clock()
        query = "SELECT EXTRACT(EPOCH FROM clock_timestamp())" if conn.dialect.name == 'postgresql' else "SELECT (julianday('now') - 2440587.5)*86400.0"
        return float(conn.execute(text(query)).scalar_one())

    def lock(self, conn, table, key, value):
        suffix = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
        return conn.execute(text(f'SELECT * FROM {table} WHERE {key}=:key'+suffix),{'key':value}).mappings().one()

    def transaction(self):
        # SQLite BEGIN IMMEDIATE serializes local writers; PostgreSQL uses rows.
        from contextlib import contextmanager
        @contextmanager
        def transaction():
            with self.store.engine.connect() as conn:
                try:
                    if conn.dialect.name == 'sqlite': conn.exec_driver_sql('BEGIN IMMEDIATE')
                    from ..identity import principal_context, assert_principal_active
                    principal=principal_context.get()
                    if principal: assert_principal_active(conn,principal)
                    from ..execution import active_job
                    job=active_job.get()
                    if job:
                        from ..workflow_store import WorkflowStore
                        WorkflowStore(self.store).validate_lease(conn,job)
                    yield conn
                    if principal: assert_principal_active(conn,principal)
                    conn.commit()
                except BaseException:
                    conn.rollback(); raise
        return transaction()

    def account(self, conn, owner):
        conn.execute(text('INSERT INTO usage_accounts(owner_id) VALUES(:owner) ON CONFLICT(owner_id) DO NOTHING'),{'owner':owner})
        return self.lock(conn,'usage_accounts','owner_id',owner)

    def accept_task_cap_in_transaction(self,conn,owner,root,maximum_micro,now):
        if not isinstance(root,str) or not root or len(root)>160 or root!=root.strip():
            raise ValueError('Task root must be an exact non-empty identifier.')
        if isinstance(maximum_micro,bool) or not isinstance(maximum_micro,int) or not 0<maximum_micro<=self.policy.grant:
            raise UsageError('usage_task_cap_invalid','Choose a task maximum within one full allowance.',422)
        self.account(conn,owner)
        existing=conn.execute(text('SELECT maximum_micro FROM usage_task_caps WHERE owner_id=:owner AND root_id=:root'),
                              {'owner':owner,'root':root}).scalar_one_or_none()
        if existing is not None:
            if existing!=maximum_micro:
                raise UsageError('usage_task_cap_conflict','This task already has a different maximum.',409)
            return
        if conn.execute(text('SELECT 1 FROM usage_reservations WHERE owner_id=:owner AND root_id=:root LIMIT 1'),
                        {'owner':owner,'root':root}).first():
            raise UsageError('usage_task_cap_conflict','A maximum must be accepted before task work starts.',409)
        self._check_task_admission_rate(conn,owner,now)
        period=conn.execute(text('SELECT id FROM usage_periods WHERE owner_id=:owner AND expires_at>:now ORDER BY starts_at DESC LIMIT 1'),
                             {'owner':owner,'now':now}).first()
        conn.execute(text('INSERT INTO usage_task_caps(owner_id,root_id,maximum_micro,period_id,policy_version,created_at) VALUES(:owner,:root,:maximum,:period,:policy,:now)'),
                     {'owner':owner,'root':root,'maximum':maximum_micro,'period':period[0] if period else None,'policy':self.policy.version,'now':now})

    def _check_task_admission_rate(self,conn,owner,now):
        recent=conn.execute(text('''SELECT created_at FROM usage_task_caps
            WHERE owner_id=:owner AND created_at>:cutoff ORDER BY created_at LIMIT :limit'''),
            {'owner':owner,'cutoff':now-60,'limit':self.USER_ADMISSIONS_PER_MINUTE}).scalars().all()
        if len(recent)>=self.USER_ADMISSIONS_PER_MINUTE:
            retry_at=float(recent[0])+60
            raise UsageError('usage_admission_rate_limited',
                'You have started several AI tasks in the last minute. Wait briefly, then try again.',
                429,reset=retry_at)

    def _task_cap(self,conn,owner,root,now):
        row=conn.execute(text('SELECT maximum_micro,period_id FROM usage_task_caps WHERE owner_id=:owner AND root_id=:root'),
                         {'owner':owner,'root':root}).first()
        if row:return row[0],row[1]
        # Non-interactive integrations still get a fixed one-window maximum,
        # so one durable root cannot consume a fresh grant after every reset.
        self._check_task_admission_rate(conn,owner,now)
        period=conn.execute(text('SELECT id FROM usage_periods WHERE owner_id=:owner AND expires_at>:now ORDER BY starts_at DESC LIMIT 1'),
                             {'owner':owner,'now':now}).first()
        conn.execute(text('INSERT INTO usage_task_caps(owner_id,root_id,maximum_micro,period_id,policy_version,created_at) VALUES(:owner,:root,:maximum,:period,:policy,:now) ON CONFLICT(owner_id,root_id) DO NOTHING'),
                     {'owner':owner,'root':root,'maximum':self.policy.grant,'period':period[0] if period else None,'policy':self.policy.version,'now':now})
        return tuple(conn.execute(text('SELECT maximum_micro,period_id FROM usage_task_caps WHERE owner_id=:owner AND root_id=:root'),
                            {'owner':owner,'root':root}).one())

    def update(self,conn,owner,now,kind='usage.updated'):
        conn.execute(text('UPDATE usage_accounts SET revision=revision+1 WHERE owner_id=:owner'),{'owner':owner})
        revision=conn.execute(text('SELECT revision FROM usage_accounts WHERE owner_id=:owner'),{'owner':owner}).scalar_one()
        conn.execute(text('INSERT INTO usage_outbox(id,owner_id,revision,created_at,kind,payload) VALUES(:id,:owner,:revision,:now,:kind,:payload)'),{'id':uuid.uuid4().hex,'owner':owner,'revision':revision,'now':now,'kind':kind,'payload':'{}'})

    @staticmethod
    def _budget_alerts(conn,platform,now):
        row=conn.execute(text('SELECT used_nano,held_nano,budget_nano FROM usage_platform_periods WHERE id=:id'),{'id':platform}).mappings().one()
        if not row['budget_nano'] or row['budget_nano']<=0:return
        total=row['used_nano']+row['held_nano'];budget=row['budget_nano']
        for threshold in (50,80,95):
            if total*100<budget*threshold:continue
            identifier=f'budget:{platform}:{threshold}'
            conn.execute(text("INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload) VALUES(:id,NULL,NULL,'platform_budget_threshold',:now,:payload) ON CONFLICT(id) DO NOTHING"),
                {'id':identifier,'now':now,'payload':json.dumps({'periodId':platform,'thresholdPercent':threshold,'usedAndHeldNano':total,'budgetNano':budget},separators=(',',':'))})

    def allowance(self,owner):
        with self.store.engine.connect() as conn:
            now=self.now(conn)
            account=conn.execute(text('SELECT * FROM usage_accounts WHERE owner_id=:owner'),{'owner':owner}).mappings().first()
            period=conn.execute(text('SELECT * FROM usage_periods WHERE owner_id=:owner AND expires_at>:now ORDER BY starts_at DESC LIMIT 1'),{'owner':owner,'now':now}).mappings().first()
            unresolved=conn.execute(text("SELECT count(*) FROM usage_reservations WHERE owner_id=:owner AND state='dispatched' AND deadline<:now"),{'owner':owner,'now':now}).scalar_one()
            p=self.policy
            grant=period['grant_micro'] if period else p.grant
            used=period['used_micro'] if period else 0
            held=period['held_micro'] if period else 0
            available=max(0,grant-used-held)
            reason='usage_capacity_unavailable' if account and (account['blocked'] or account['status']!='active') else 'usage_reconciliation_pending' if unresolved else 'usage_window_exhausted' if not available else None
            return dict(policyVersion=period['policy_version'] if period else p.version,rateVersion=p.rates,windowId=period['id'] if period else None,windowState='active' if period else 'ready',serverTime=now,startsAt=period['starts_at'] if period else None,resetsAt=period['expires_at'] if period else None,grantedMicrocredits=grant,usedMicrocredits=used,heldMicrocredits=held,availableMicrocredits=available,revision=account['revision'] if account else 0,availability='unavailable' if reason else 'available',reasonCode=reason)

    def reserve(self,owner,key,component,quantities,liability=0,root=None,seconds=240,provider=None,model=None,provider_rates=None):
        p=self.policy
        amount=price(component,quantities,liability)
        if amount<=0: raise ValueError('Reservation must have a positive bound.')
        request_hash=hashlib.sha256(json.dumps([component,quantities,liability,root,provider,model,provider_rates],sort_keys=True).encode()).hexdigest()
        with self.transaction() as conn:
            now=self.now(conn)
            # A settled idempotent replay must remain readable even when the
            # platform budget is now full. A concurrent first admission is
            # still serialized by the owner row below.
            previous=conn.execute(text('SELECT * FROM usage_reservations WHERE owner_id=:owner AND operation_key=:key'),{'owner':owner,'key':key}).mappings().first()
            if previous:
                if previous['request_hash']!=request_hash: raise UsageError('usage_operation_conflict','This operation key was used for different work.',409)
                return dict(previous)
            capability=_usage_capability(component,provider,model,quantities)
            disabled=conn.execute(text("SELECT capability FROM usage_capability_controls WHERE disabled=true AND capability IN ('all',:capability) LIMIT 1"),{'capability':capability}).first()
            if disabled:
                raise UsageError('usage_capability_disabled','This capability is temporarily disabled by an operator.',503)
            utc=datetime.fromtimestamp(now,timezone.utc)
            day='day:'+utc.strftime('%Y-%m-%d'); month='month:'+utc.strftime('%Y-%m')
            for platform,cap in ((month,p.monthly),(day,p.daily)):
                conn.execute(text('INSERT INTO usage_platform_periods(id) VALUES(:id) ON CONFLICT(id) DO NOTHING'),{'id':platform})
                row=self.lock(conn,'usage_platform_periods','id',platform)
                budget=row['budget_nano'] if row['budget_nano'] is not None else cap
                if row['budget_nano'] is None:
                    conn.execute(text('UPDATE usage_platform_periods SET budget_nano=:budget WHERE id=:id AND budget_nano IS NULL'),{'budget':budget,'id':platform})
                if row['blocked'] or liability and row['used_nano']+row['held_nano']+liability>budget:
                    raise UsageError('usage_capacity_unavailable','AI service capacity is temporarily unavailable.',503)
            account=self.account(conn,owner)
            if account['blocked'] or account['status']!='active': raise UsageError('usage_capacity_unavailable','AI work is paused while usage is reconciled.',503)
            previous=conn.execute(text('SELECT * FROM usage_reservations WHERE owner_id=:owner AND operation_key=:key'),{'owner':owner,'key':key}).mappings().first()
            if previous:
                if previous['request_hash']!=request_hash: raise UsageError('usage_operation_conflict','This operation key was used for different work.',409)
                return dict(previous)
            if conn.execute(text("SELECT 1 FROM usage_reservations WHERE owner_id=:owner AND state='dispatched' AND deadline<:now LIMIT 1"),{'owner':owner,'now':now}).first():
                raise UsageError('usage_reconciliation_pending','Previous AI work is being reconciled.',503)
            task_root=root or key
            task_cap,task_period=self._task_cap(conn,owner,task_root,now)
            task_used=conn.execute(text("SELECT COALESCE(SUM(microcredits),0) FROM usage_events WHERE owner_id=:owner AND root_id=:root AND source NOT IN ('released','adjustment')"),
                                   {'owner':owner,'root':task_root}).scalar_one()
            task_held=conn.execute(text("SELECT COALESCE(SUM(held_micro),0) FROM usage_reservations WHERE owner_id=:owner AND root_id=:root AND state IN ('reserved','dispatched')"),
                                   {'owner':owner,'root':task_root}).scalar_one()
            if task_used+task_held+amount>task_cap:
                raise UsageError('usage_task_cap_exhausted','This task reached its accepted maximum. Its saved work is available; start a linked task to continue.',409)
            if p.provider_rate_version and provider_rates:
                rate_provider=provider or component
                if model: rate_provider+=':'+model
                card_id=p.provider_rate_version+':'+rate_provider
                snapshot=json.dumps(provider_rates,sort_keys=True,separators=(',',':'))
                conn.execute(text('INSERT INTO usage_provider_rate_cards(id,version,provider,payload,created_at) VALUES(:id,:version,:provider,:payload,:now) ON CONFLICT DO NOTHING'),
                             {'id':card_id,'version':p.provider_rate_version,'provider':rate_provider,'payload':snapshot,'now':now})
                pinned=conn.execute(text('SELECT payload FROM usage_provider_rate_cards WHERE id=:id'),{'id':card_id}).scalar_one()
                if pinned!=snapshot:
                    raise UsageError('usage_rate_version_conflict','Configured provider rates changed without a new rate version.',503)
            period=conn.execute(text('SELECT * FROM usage_periods WHERE owner_id=:owner AND expires_at>:now ORDER BY starts_at DESC LIMIT 1'),{'owner':owner,'now':now}).mappings().first()
            if task_period and (not period or period['id']!=task_period):
                raise UsageError('usage_task_window_changed','This task stopped at the allowance refresh. Start a linked task to continue; saved work is preserved.',409)
            if amount>(period['grant_micro']-period['used_micro']-period['held_micro'] if period else p.grant):
                raise UsageError('usage_window_exhausted','Not enough allowance for this task. Your work is saved.',reset=period['expires_at'] if period else None)
            if not period:
                pid=uuid.uuid4().hex
                conn.execute(text('INSERT INTO usage_periods(id,owner_id,starts_at,expires_at,grant_micro,policy_version) VALUES(:id,:owner,:now,:end,:grant,:policy)'),{'id':pid,'owner':owner,'now':now,'end':now+p.seconds,'grant':p.grant,'policy':p.version})
                period=self.lock(conn,'usage_periods','id',pid)
            if not task_period:
                conn.execute(text('UPDATE usage_task_caps SET period_id=:period WHERE owner_id=:owner AND root_id=:root AND period_id IS NULL'),
                             {'period':period['id'],'owner':owner,'root':task_root})
            conn.execute(text('UPDATE usage_accounts SET current_period_id=:period WHERE owner_id=:owner'),{'period':period['id'],'owner':owner})
            rid=uuid.uuid4().hex
            payload=json.dumps({'maximumQuantities':quantities,'providerRates':provider_rates or {}},separators=(',',':'))
            values={'id':rid,'owner':owner,'period':period['id'],'key':key,'hash':request_hash,'component':component,'root':root or key,'amount':amount,'liability':liability,'day':day,'month':month,'now':now,'deadline':now+seconds,'rates':p.rates,'payload':payload}
            values.update(provider=provider,model=model,provider_rate_version=p.provider_rate_version or None)
            conn.execute(text("INSERT INTO usage_reservations(id,owner_id,period_id,operation_key,request_hash,component,root_id,state,held_micro,liability_nano,day_id,month_id,created_at,deadline,rate_version,payload,provider,model,provider_rate_version) VALUES(:id,:owner,:period,:key,:hash,:component,:root,'reserved',:amount,:liability,:day,:month,:now,:deadline,:rates,:payload,:provider,:model,:provider_rate_version)"),values)
            conn.execute(text('UPDATE usage_periods SET held_micro=held_micro+:amount WHERE id=:id'),{'amount':amount,'id':period['id']})
            for platform in (month,day):
                conn.execute(text('UPDATE usage_platform_periods SET held_nano=held_nano+:amount WHERE id=:id'),{'amount':liability,'id':platform})
                self._budget_alerts(conn,platform,now)
            self.update(conn,owner,now)
            return dict(conn.execute(text('SELECT * FROM usage_reservations WHERE id=:id'),{'id':rid}).mappings().one())

    def dispatch(self,owner,rid):
        with self.transaction() as conn:
            self.account(conn,owner)
            now=self.now(conn)
            updated=conn.execute(text("UPDATE usage_reservations SET state='dispatched',dispatched_at=:now WHERE id=:id AND owner_id=:owner AND state='reserved' AND deadline>:now"),{'id':rid,'owner':owner,'now':now})
            if updated.rowcount!=1:raise UsageError('usage_operation_conflict','This operation has already been dispatched or expired.',409)

    def settle(self,owner,rid,quantities=None,cost=0,source='exact',release=False,provider=None,model=None,receipt_id=None):
        with self.transaction() as conn:
            r=conn.execute(text('SELECT * FROM usage_reservations WHERE id=:id AND owner_id=:owner'),{'id':rid,'owner':owner}).mappings().first()
            if not r:raise UsageError('usage_operation_conflict','Usage operation not found.',404)
            for platform in (r['month_id'],r['day_id']):self.lock(conn,'usage_platform_periods','id',platform)
            self.account(conn,owner)
            r=self.lock(conn,'usage_reservations','id',rid)
            if r['state'] in {'settled','released'}:return
            if release and r['state']!='reserved':raise ValueError('Dispatched liability cannot be released without a receipt.')
            # An undispatched reservation never reached the provider, so
            # reclaim its hold without recording a provider cost.
            settled_cost=0 if release else cost
            raw=0 if release else price(r['component'],quantities or json.loads(r['payload'])['maximumQuantities'],settled_cost)
            debit=min(raw,r['held_micro'])
            overrun=raw>r['held_micro'] or settled_cost>r['liability_nano']
            if overrun:
                conn.execute(text('UPDATE usage_accounts SET blocked=:blocked WHERE owner_id=:owner'),{'blocked':True,'owner':owner})
            conn.execute(text('UPDATE usage_periods SET held_micro=held_micro-:held,used_micro=used_micro+:debit WHERE id=:id'),{'held':r['held_micro'],'debit':debit,'id':r['period_id']})
            now=self.now(conn)
            for platform in (r['month_id'],r['day_id']):
                conn.execute(text('UPDATE usage_platform_periods SET held_nano=held_nano-:held,used_nano=used_nano+:cost WHERE id=:id'),{'held':r['liability_nano'],'cost':settled_cost,'id':platform})
                self._budget_alerts(conn,platform,now)
            provider=provider or r['provider'];model=model or r['model']
            conn.execute(text('UPDATE usage_reservations SET state=:state,settled_at=:now,provider=:provider,model=:model,receipt_id=:receipt,receipt_at=:receipt_at WHERE id=:id'),{'state':'released' if release else 'settled','now':now,'provider':provider,'model':model,'receipt':receipt_id,'receipt_at':now if receipt_id else None,'id':rid})
            conn.execute(text('INSERT INTO usage_events(id,owner_id,reservation_id,period_id,root_id,component,microcredits,cost_nano,source,created_at,payload,provider,model,currency,receipt_id,provider_rate_version) VALUES(:id,:owner,:id,:period,:root,:component,:debit,:cost,:source,:now,:payload,:provider,:model,\'USD\',:receipt,:provider_rate_version)'),{'id':rid,'owner':owner,'period':r['period_id'],'root':r['root_id'],'component':r['component'],'debit':debit,'cost':settled_cost,'source':'released' if release else source,'now':now,'payload':json.dumps(quantities or {}),'provider':provider,'model':model,'receipt':receipt_id,'provider_rate_version':r['provider_rate_version']})
            if overrun:
                conn.execute(text("INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload) VALUES(:id,:owner,:reservation,'provider_liability_overrun',:now,:payload) ON CONFLICT(id) DO NOTHING"),{'id':'overrun:'+rid,'owner':owner,'reservation':rid,'now':now,'payload':json.dumps({'heldMicrocredits':r['held_micro'],'actualMicrocredits':raw,'heldLiabilityNano':r['liability_nano'],'actualLiabilityNano':settled_cost},separators=(',',':'))})
            self.update(conn,owner,now)

    @staticmethod
    def _encode_cursor(created_at,root_id,period_id):
        raw=json.dumps([created_at,root_id,period_id],separators=(',',':')).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip('=')

    @staticmethod
    def _decode_cursor(value):
        if value is None:return None
        try:
            raw=base64.urlsafe_b64decode(value+'='*((4-len(value)%4)%4))
            created,root,period=json.loads(raw)
            if not isinstance(created,(int,float)) or not isinstance(root,str) or not isinstance(period,str):raise ValueError()
            return float(created),root,period
        except Exception:
            raise UsageError('usage_cursor_invalid','Refresh the usage activity list and try again.',422) from None

    def activity(self,owner,cursor=None,limit=30,include_components=True):
        with self.store.engine.connect() as conn:
            decoded=self._decode_cursor(cursor)
            params={'owner':owner,'limit':limit+1,'cursorTime':decoded[0] if decoded else float('inf'),
                    'cursorRoot':decoded[1] if decoded else '', 'cursorPeriod':decoded[2] if decoded else ''}
            rows=conn.execute(text('''WITH task_entries AS (
                SELECT e.root_id,e.period_id,e.created_at,e.microcredits,0 AS held_micro,e.source,e.component
                FROM usage_events e WHERE e.owner_id=:owner AND e.source<>'released'
                UNION ALL
                SELECT r.root_id,r.period_id,r.created_at,0 AS microcredits,r.held_micro,'pending' AS source,r.component
                FROM usage_reservations r WHERE r.owner_id=:owner AND r.state IN ('reserved','dispatched')
            ), grouped AS (
                SELECT t.root_id,t.period_id,p.grant_micro,MAX(t.created_at) AS created_at,
                       SUM(t.microcredits) AS microcredits,SUM(t.held_micro) AS held_micro,
                       CASE WHEN MAX(CASE WHEN t.source='estimated' THEN 1 ELSE 0 END)=1 THEN 'estimated'
                            WHEN SUM(t.held_micro)>0 AND SUM(t.microcredits)=0 THEN 'pending' ELSE 'exact' END AS source,
                       CASE WHEN SUM(t.held_micro)>0 AND SUM(t.microcredits)<>0 THEN 'in_progress'
                            WHEN SUM(t.held_micro)>0 THEN 'pending' ELSE 'settled' END AS status
                FROM task_entries t JOIN usage_periods p ON p.id=t.period_id
                GROUP BY t.root_id,t.period_id,p.grant_micro
            ) SELECT * FROM grouped WHERE created_at<:cursorTime
                OR (created_at=:cursorTime AND root_id<:cursorRoot)
                OR (created_at=:cursorTime AND root_id=:cursorRoot AND period_id<:cursorPeriod)
                ORDER BY created_at DESC,root_id DESC,period_id DESC LIMIT :limit'''),params).mappings().all()
            more=len(rows)>limit
            rows=rows[:limit]
            items=[dict(r,id=f"{r['root_id']}:{r['period_id']}",component='task',components=[],adjustments=[]) for r in rows]
            adjustment_items=[]
            if rows:
                keys={(r['root_id'],r['period_id']):item for r,item in zip(rows,items)}
                binds={'owner':owner}
                for i,(root,period) in enumerate(keys):
                    binds[f'root{i}']=root;binds[f'period{i}']=period
                if include_components:
                    filters=[]
                    for i in range(len(keys)):
                        filters.append(f'(t.root_id=:root{i} AND t.period_id=:period{i})')
                    entries='''WITH task_entries AS (
                        SELECT e.root_id,e.period_id,e.created_at,e.microcredits,0 AS held_micro,e.source,e.component
                        FROM usage_events e WHERE e.owner_id=:owner AND e.source<>'released'
                        UNION ALL
                        SELECT r.root_id,r.period_id,r.created_at,0 AS microcredits,r.held_micro,'pending' AS source,r.component
                        FROM usage_reservations r WHERE r.owner_id=:owner AND r.state IN ('reserved','dispatched')
                    ) '''
                    comps=conn.execute(text(entries+'''SELECT t.root_id,t.period_id,t.component,SUM(t.microcredits) AS microcredits,
                        SUM(t.held_micro) AS held_micro,MAX(t.created_at) AS created_at,
                        CASE WHEN MAX(CASE WHEN t.source='estimated' THEN 1 ELSE 0 END)=1 THEN 'estimated'
                             WHEN SUM(t.held_micro)>0 AND SUM(t.microcredits)=0 THEN 'pending' ELSE 'exact' END AS source
                        FROM task_entries t WHERE '''+ ' OR '.join(filters) + '''
                        GROUP BY t.root_id,t.period_id,t.component'''),binds).mappings().all()
                    for c in comps:
                        item=keys.get((c['root_id'],c['period_id']))
                        if item:item['components'].append(dict(c))
                adjustments=conn.execute(text('''SELECT e.root_id,e.period_id,e.id,e.component,e.microcredits,e.created_at,e.payload
                    FROM usage_events e WHERE e.owner_id=:owner AND e.source='adjustment' AND ('''+
                    ' OR '.join(f'(e.root_id=:root{i} AND e.period_id=:period{i})' for i in range(len(keys))) + ''')
                    ORDER BY e.created_at DESC,e.id'''),binds).mappings().all()
                for adjustment in adjustments:
                    item=keys.get((adjustment['root_id'],adjustment['period_id']))
                    if item:
                        try:kind=json.loads(adjustment['payload']).get('kind','adjustment')
                        except (TypeError,ValueError):kind='adjustment'
                        receipt={'id':adjustment['id'],'component':adjustment['component'],
                            'kind':kind,'microcredits':adjustment['microcredits'],'created_at':adjustment['created_at']}
                        item['adjustments'].append(receipt)
                        adjustment_items.append(receipt)
            next_cursor=self._encode_cursor(rows[-1]['created_at'],rows[-1]['root_id'],rows[-1]['period_id']) if more and rows else None
            return {'items':items,'adjustments':adjustment_items,'nextCursor':next_cursor}

    def monitor(self, outbox_threshold=None):
        """Queue operational alerts for stale reconciliation and outbox growth.

        The outbox is intentionally never pruned here. Its per-owner revision
        is a cheap exact count while retention remains disabled, and clients
        continue to receive every replayable revision.
        """
        threshold = self.OUTBOX_ALERT_ROWS if outbox_threshold is None else outbox_threshold
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError('Outbox alert threshold must be a positive integer.')
        with self.transaction() as conn:
            now = self.now(conn)
            stale = conn.execute(text("""SELECT id,owner_id,deadline FROM usage_reservations
                WHERE state='dispatched' AND deadline+:grace<:now ORDER BY deadline LIMIT 100"""),
                {'grace': self.RECONCILIATION_ALERT_GRACE_SECONDS, 'now': now}).mappings().all()
            for reservation in stale:
                alert_id = 'reconciliation-lag:' + reservation['id']
                conn.execute(text("""INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload)
                    VALUES(:id,:owner,:reservation,'usage_reconciliation_lag',:now,:payload)
                    ON CONFLICT(id) DO NOTHING"""), {
                    'id': alert_id, 'owner': reservation['owner_id'], 'reservation': reservation['id'],
                    'now': now, 'payload': json.dumps({
                        'deadline': reservation['deadline'],
                        'lagSeconds': max(0, int(now - reservation['deadline'])),
                    }, separators=(',', ':')),
                })
            # Every account revision creates exactly one durable outbox row.
            # This avoids a full COUNT scan of the growing replay table.
            event_count = int(conn.execute(text('SELECT COALESCE(SUM(revision),0) FROM usage_accounts')).scalar_one())
            if event_count >= threshold:
                utc_day = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d')
                conn.execute(text("""INSERT INTO usage_alerts(id,owner_id,reservation_id,kind,created_at,payload)
                    VALUES(:id,NULL,NULL,'usage_outbox_growth',:now,:payload) ON CONFLICT(id) DO NOTHING"""), {
                    'id': f'usage-outbox-growth:{utc_day}', 'now': now,
                    'payload': json.dumps({'eventCount': event_count, 'pruningEnabled': False}, separators=(',', ':')),
                })
            return {'staleReconciliationCount': len(stale), 'outboxEventCount': event_count}

    def reconcile(self):
        with self.store.engine.connect() as conn:
            now=self.now(conn)
            rows=conn.execute(text("SELECT * FROM usage_reservations WHERE state IN ('reserved','dispatched') AND deadline<:now LIMIT 100"),{'now':now}).mappings().all()
        for r in rows:
            self.settle(r['owner_id'],r['id'],cost=r['liability_nano'],source='estimated',release=r['state']=='reserved')
        return len(rows)

    def unblock(self,owner,actor,reason):
        """Audited operator recovery after provider uncertainty has been resolved."""
        if not isinstance(actor,str) or not actor.strip() or len(actor)>160:
            raise ValueError('A named operator is required.')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>500:
            raise ValueError('A concise recovery reason is required.')
        with self.transaction() as conn:
            account=self.account(conn,owner)
            if account['status']!='active':
                raise UsageError('usage_capacity_unavailable','This account is not active.',409)
            pending=conn.execute(text("SELECT count(*) FROM usage_reservations WHERE owner_id=:owner AND state IN ('reserved','dispatched')"),{'owner':owner}).scalar_one()
            if pending:
                raise UsageError('usage_reconciliation_pending','Resolve every held or dispatched provider operation before unblocking.',409)
            if not account['blocked']:
                return False
            now=self.now(conn)
            conn.execute(text('UPDATE usage_accounts SET blocked=false WHERE owner_id=:owner'),{'owner':owner})
            conn.execute(text("INSERT INTO usage_adjustments(id,owner_id,actor,reason,kind,microcredits,created_at) VALUES(:id,:owner,:actor,:reason,'unblock',0,:now)"),
                         {'id':'adjustment:'+uuid.uuid4().hex,'owner':owner,'actor':actor.strip(),'reason':reason.strip(),'now':now})
            self.update(conn,owner,now,'usage.operator_unblocked')
            return True
