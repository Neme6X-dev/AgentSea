"""Plateforme SaaS : rôles, offres, régionalisation, file de travaux, analytics, audit.

Deux précautions que l'autogénération d'Alembic ne prend pas, et qui feraient échouer
cette migration sur une base contenant déjà des comptes :

1. **Colonnes NOT NULL ajoutées avec `server_default`.** Sans valeur par défaut,
   PostgreSQL refuse d'ajouter une colonne non nulle à une table peuplée. Les défauts
   sont conservés après coup : ils documentent le comportement attendu et protègent
   les insertions faites hors ORM (scripts d'import, correctifs manuels).

2. **Conversion des horodatages avec `USING`.** Passer `VARCHAR` à `TIMESTAMPTZ`
   suppose une conversion explicite ; sans elle, PostgreSQL répond « column cannot be
   cast automatically ». Les valeurs existantes sont des chaînes ISO 8601 UTC écrites
   par l'ancienne version du code, donc `::timestamptz` les interprète correctement.

Revision ID: 29a338972d74
Revises: 6723c9482c42
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29a338972d74'
down_revision: Union[str, Sequence[str], None] = '6723c9482c42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Applique le schéma de la plateforme SaaS."""
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_email', sa.String(length=254), nullable=True),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('changes', sa.Text(), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_actor', 'audit_log', ['actor_id'], unique=False)
    op.create_index('ix_audit_target', 'audit_log', ['target_type', 'target_id'], unique=False)
    op.create_index('ix_audit_ts', 'audit_log', ['ts'], unique=False)
    op.create_table('auth_attempts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=320), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_auth_attempts_key_ts', 'auth_attempts', ['key', 'ts'], unique=False)
    op.create_table('events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('name', sa.String(length=48), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('session_id', sa.String(length=12), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('props', sa.Text(), nullable=False),
    sa.Column('ip_hash', sa.String(length=16), nullable=True),
    sa.Column('user_agent', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_name_ts', 'events', ['name', 'ts'], unique=False)
    op.create_index('ix_events_ts', 'events', ['ts'], unique=False)
    op.create_index('ix_events_user', 'events', ['user_id'], unique=False)
    op.create_table('feature_flags',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('rollout_percent', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_by', sa.String(length=254), nullable=True),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('jobs',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=64), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('session_id', sa.String(length=12), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_claim', 'jobs', ['status', 'priority', 'run_at'], unique=False)
    op.create_index('ix_jobs_created', 'jobs', ['created_at'], unique=False)
    op.create_index('ix_jobs_session', 'jobs', ['session_id'], unique=False)
    op.create_table('llm_calls',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('agent', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=12), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('error', sa.String(length=200), nullable=True),
    sa.Column('cost_xof', sa.Float(), nullable=False),
    sa.Column('key_index', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_llm_agent', 'llm_calls', ['agent'], unique=False)
    op.create_index('ix_llm_session', 'llm_calls', ['session_id'], unique=False)
    op.create_index('ix_llm_ts', 'llm_calls', ['ts'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=24), nullable=False),
    sa.Column('period', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount_xof', sa.Integer(), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=True),
    sa.Column('provider_ref', sa.String(length=120), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subs_started', 'subscriptions', ['started_at'], unique=False)
    op.create_index('ix_subs_user', 'subscriptions', ['user_id'], unique=False)
    op.create_table('usage_counters',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('metric', sa.String(length=32), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'period', 'metric', name='uq_usage_user_period_metric')
    )
    op.create_table('site_visits',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=12), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('views', sa.Integer(), nullable=False),
    sa.Column('visitors', sa.Integer(), nullable=False),
    sa.Column('whatsapp_clicks', sa.Integer(), nullable=False),
    sa.Column('call_clicks', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'day', 'country', name='uq_visit_session_day_country')
    )
    op.create_index('ix_visits_day', 'site_visits', ['day'], unique=False)
    op.alter_column('artifacts', 'created_at',
               existing_type=sa.VARCHAR(length=32),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False,
               postgresql_using='created_at::timestamptz')
    op.create_index('ix_artifacts_session_kind', 'artifacts', ['session_id', 'kind'], unique=False)
    op.add_column('sessions', sa.Column('country', sa.String(length=2), nullable=False, server_default=sa.text("'BJ'")))
    op.add_column('sessions', sa.Column('business_type', sa.String(length=40), nullable=True))
    op.add_column('sessions', sa.Column('template_id', sa.String(length=64), nullable=True))
    op.add_column('sessions', sa.Column('custom_domain', sa.String(length=191), nullable=True))
    op.add_column('sessions', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('sessions', 'created_at',
               existing_type=sa.VARCHAR(length=32),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False,
               postgresql_using='created_at::timestamptz')
    op.alter_column('sessions', 'updated_at',
               existing_type=sa.VARCHAR(length=32),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False,
               postgresql_using='updated_at::timestamptz')
    op.create_index('ix_sessions_country', 'sessions', ['country'], unique=False)
    op.create_index('ix_sessions_created_at', 'sessions', ['created_at'], unique=False)
    op.create_index('ix_sessions_status', 'sessions', ['status'], unique=False)
    op.create_index('ix_sessions_user', 'sessions', ['user_id'], unique=False)
    op.add_column('users', sa.Column('role', sa.String(length=16), nullable=False, server_default=sa.text("'user'")))
    op.add_column('users', sa.Column('plan', sa.String(length=24), nullable=False, server_default=sa.text("'decouverte'")))
    op.add_column('users', sa.Column('plan_period', sa.String(length=8), nullable=False, server_default=sa.text("'monthly'")))
    op.add_column('users', sa.Column('status', sa.String(length=16), nullable=False, server_default=sa.text("'active'")))
    op.add_column('users', sa.Column('country', sa.String(length=2), nullable=False, server_default=sa.text("'BJ'")))
    op.add_column('users', sa.Column('city', sa.String(length=80), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(length=24), nullable=True))
    op.add_column('users', sa.Column('whatsapp', sa.String(length=24), nullable=True))
    op.add_column('users', sa.Column('company', sa.String(length=160), nullable=True))
    op.add_column('users', sa.Column('locale', sa.String(length=5), nullable=False, server_default=sa.text("'fr'")))
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('suspension_reason', sa.Text(), nullable=True))
    op.alter_column('users', 'created_at',
               existing_type=sa.VARCHAR(length=32),
               type_=sa.DateTime(timezone=True),
               existing_nullable=False,
               postgresql_using='created_at::timestamptz')
    op.create_index('ix_users_country', 'users', ['country'], unique=False)
    op.create_index('ix_users_created_at', 'users', ['created_at'], unique=False)
    op.create_index('ix_users_plan', 'users', ['plan'], unique=False)
    op.create_index('ix_users_role', 'users', ['role'], unique=False)


def downgrade() -> None:
    """Revient au schéma initial. Les données analytiques sont perdues, par nature."""
    op.drop_index('ix_users_role', table_name='users')
    op.drop_index('ix_users_plan', table_name='users')
    op.drop_index('ix_users_created_at', table_name='users')
    op.drop_index('ix_users_country', table_name='users')
    op.alter_column('users', 'created_at',
               existing_type=sa.DateTime(timezone=True),
               type_=sa.VARCHAR(length=32),
               existing_nullable=False,
               postgresql_using="to_char(created_at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')")
    op.drop_column('users', 'suspension_reason')
    op.drop_column('users', 'suspended_at')
    op.drop_column('users', 'last_seen_at')
    op.drop_column('users', 'locale')
    op.drop_column('users', 'company')
    op.drop_column('users', 'whatsapp')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'city')
    op.drop_column('users', 'country')
    op.drop_column('users', 'status')
    op.drop_column('users', 'plan_period')
    op.drop_column('users', 'plan')
    op.drop_column('users', 'role')
    op.drop_index('ix_sessions_user', table_name='sessions')
    op.drop_index('ix_sessions_status', table_name='sessions')
    op.drop_index('ix_sessions_created_at', table_name='sessions')
    op.drop_index('ix_sessions_country', table_name='sessions')
    op.alter_column('sessions', 'updated_at',
               existing_type=sa.DateTime(timezone=True),
               type_=sa.VARCHAR(length=32),
               existing_nullable=False,
               postgresql_using="to_char(updated_at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')")
    op.alter_column('sessions', 'created_at',
               existing_type=sa.DateTime(timezone=True),
               type_=sa.VARCHAR(length=32),
               existing_nullable=False,
               postgresql_using="to_char(created_at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')")
    op.drop_column('sessions', 'archived_at')
    op.drop_column('sessions', 'published_at')
    op.drop_column('sessions', 'custom_domain')
    op.drop_column('sessions', 'template_id')
    op.drop_column('sessions', 'business_type')
    op.drop_column('sessions', 'country')
    op.drop_index('ix_artifacts_session_kind', table_name='artifacts')
    op.alter_column('artifacts', 'created_at',
               existing_type=sa.DateTime(timezone=True),
               type_=sa.VARCHAR(length=32),
               existing_nullable=False,
               postgresql_using="to_char(created_at at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')")
    op.drop_index('ix_visits_day', table_name='site_visits')
    op.drop_table('site_visits')
    op.drop_table('usage_counters')
    op.drop_index('ix_subs_user', table_name='subscriptions')
    op.drop_index('ix_subs_started', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index('ix_llm_ts', table_name='llm_calls')
    op.drop_index('ix_llm_session', table_name='llm_calls')
    op.drop_index('ix_llm_agent', table_name='llm_calls')
    op.drop_table('llm_calls')
    op.drop_index('ix_jobs_session', table_name='jobs')
    op.drop_index('ix_jobs_created', table_name='jobs')
    op.drop_index('ix_jobs_claim', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('feature_flags')
    op.drop_index('ix_events_user', table_name='events')
    op.drop_index('ix_events_ts', table_name='events')
    op.drop_index('ix_events_name_ts', table_name='events')
    op.drop_table('events')
    op.drop_index('ix_auth_attempts_key_ts', table_name='auth_attempts')
    op.drop_table('auth_attempts')
    op.drop_index('ix_audit_ts', table_name='audit_log')
    op.drop_index('ix_audit_target', table_name='audit_log')
    op.drop_index('ix_audit_actor', table_name='audit_log')
    op.drop_table('audit_log')
